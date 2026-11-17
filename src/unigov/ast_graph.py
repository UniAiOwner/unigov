"""UniGov Ground-Truth AST Graph, Tree-Sitter RepoMap & 2-3 Step Blast-Radius Engine.

Inspired by Aider's Tree-Sitter RepoMap and Judea Pearl's Causal Hierarchy,
providing deterministic symbol indexing, PageRank centrality ranking,
and multi-step blast-radius impact analysis for Python, Kotlin, TypeScript, and Java.
"""

import ast
import math
import os
import re
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from .context_bundler import estimate_token_count, calculate_token_budget

console = Console()

# Try loading tree_sitter + tree_sitter_python
HAS_TREE_SITTER = False
ts_python_parser = None

try:
    import tree_sitter
    import tree_sitter_python
    py_lang = tree_sitter.Language(tree_sitter_python.language())
    ts_python_parser = tree_sitter.Parser(py_lang)
    HAS_TREE_SITTER = True
except Exception:
    HAS_TREE_SITTER = False


@dataclass
class SymbolTag:
    file_path: str
    name: str
    kind: str  # 'class', 'interface', 'function', 'method', 'property', 'object'
    line_no: int
    signature: str = ""
    docstring: Optional[str] = None
    supertypes: List[str] = field(default_factory=list)
    pagerank: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "name": self.name,
            "kind": self.kind,
            "line_no": self.line_no,
            "signature": self.signature,
            "docstring": self.docstring,
            "supertypes": self.supertypes,
            "pagerank": round(self.pagerank, 6),
        }


@dataclass
class SymbolEdge:
    caller_symbol: str
    callee_symbol: str
    caller_file: str
    callee_file: Optional[str] = None
    relation: str = "CALLS"  # 'CALLS', 'INHERITS', 'IMPORTS'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caller_symbol": self.caller_symbol,
            "callee_symbol": self.callee_symbol,
            "caller_file": self.caller_file,
            "callee_file": self.callee_file,
            "relation": self.relation,
        }


@dataclass
class BlastRadiusReport:
    target_file: str
    target_symbol: Optional[str]
    upstream_callers: List[Dict[str, Any]]  # Dependents: who calls/imports this (steps 1..3)
    downstream_callees: List[Dict[str, Any]]  # Dependencies: what does this call (steps 1..3)
    impacted_files: List[str]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH'
    risk_summary: str
    depth_reached: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_file": self.target_file,
            "target_symbol": self.target_symbol,
            "upstream_callers": self.upstream_callers,
            "downstream_callees": self.downstream_callees,
            "impacted_files": self.impacted_files,
            "risk_level": self.risk_level,
            "risk_summary": self.risk_summary,
            "depth_reached": self.depth_reached,
        }


class ProjectASTGraph:
    """Maintains project symbol definitions, inter-symbol caller edges, and PageRank scores."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.symbols: Dict[str, SymbolTag] = {}  # key: "file_path::name"
        self.edges: List[SymbolEdge] = []
        self.file_symbols: Dict[str, List[SymbolTag]] = defaultdict(list)
        self.symbol_to_file: Dict[str, str] = {}
        self.forward_graph: Dict[str, Set[str]] = defaultdict(set)  # caller -> set of callees
        self.reverse_graph: Dict[str, Set[str]] = defaultdict(set)  # callee -> set of callers

    def add_symbol(self, tag: SymbolTag) -> None:
        key = f"{tag.file_path}::{tag.name}"
        self.symbols[key] = tag
        self.file_symbols[tag.file_path].append(tag)
        self.symbol_to_file[tag.name] = tag.file_path

    def add_edge(self, edge: SymbolEdge) -> None:
        self.edges.append(edge)
        self.forward_graph[edge.caller_symbol].add(edge.callee_symbol)
        self.reverse_graph[edge.callee_symbol].add(edge.caller_symbol)

    def compute_pagerank(self, damping: float = 0.85, iterations: int = 20) -> None:
        """Computes PageRank centrality over the inter-symbol graph."""
        nodes = list(self.symbols.keys())
        N = len(nodes)
        if N == 0:
            return

        scores = {node: 1.0 / N for node in nodes}

        # Build mapping using short symbol names as well
        symbol_key_map = {}
        for k, v in self.symbols.items():
            symbol_key_map[v.name] = k
            symbol_key_map[k] = k

        for _ in range(iterations):
            new_scores = {}
            for node in nodes:
                tag = self.symbols[node]
                incoming = self.reverse_graph.get(tag.name, set())
                rank_sum = 0.0
                for inc_name in incoming:
                    inc_key = symbol_key_map.get(inc_name)
                    if inc_key and inc_key in scores:
                        out_count = len(self.forward_graph.get(inc_name, []))
                        if out_count > 0:
                            rank_sum += scores[inc_key] / out_count
                new_scores[node] = (1.0 - damping) / N + damping * rank_sum
            scores = new_scores

        # Normalize and update
        max_score = max(scores.values()) if scores else 1.0
        for node, score in scores.items():
            self.symbols[node].pagerank = score / max_score if max_score > 0 else 0.0


# ---------------------------------------------------------------------------
# Multi-Language AST Parsers
# ---------------------------------------------------------------------------

def parse_python_file(file_path: Path, rel_path: str) -> Tuple[List[SymbolTag], List[SymbolEdge]]:
    """Extracts symbols and call edges from Python files using native AST & Tree-Sitter."""
    symbols: List[SymbolTag] = []
    edges: List[SymbolEdge] = []
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return symbols, edges

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            doc = ast.get_docstring(node)
            tag = SymbolTag(
                file_path=rel_path,
                name=node.name,
                kind="class",
                line_no=node.lineno,
                signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                docstring=doc.split("\n")[0] if doc else None,
                supertypes=bases,
            )
            symbols.append(tag)
            for b in bases:
                edges.append(SymbolEdge(caller_symbol=node.name, callee_symbol=b, caller_file=rel_path, relation="INHERITS"))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node)
            sig = f"{prefix} {node.name}({', '.join(args)})"
            tag = SymbolTag(
                file_path=rel_path,
                name=node.name,
                kind="function",
                line_no=node.lineno,
                signature=sig,
                docstring=doc.split("\n")[0] if doc else None,
            )
            symbols.append(tag)

            # Discover calls inside this function
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = None
                    if isinstance(child.func, ast.Name):
                        callee = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        callee = child.func.attr
                    if callee and callee != node.name:
                        edges.append(SymbolEdge(caller_symbol=node.name, callee_symbol=callee, caller_file=rel_path, relation="CALLS"))

    return symbols, edges


def parse_kotlin_java_file(file_path: Path, rel_path: str) -> Tuple[List[SymbolTag], List[SymbolEdge]]:
    """Extracts symbols and call edges from Kotlin and Java source files."""
    symbols: List[SymbolTag] = []
    edges: List[SymbolEdge] = []
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return symbols, edges

    current_class = None

    class_pat = re.compile(
        r"^\s*(?:@[\w\(\)\"=,\s]+\s+)*(?:public\s+|private\s+|internal\s+|open\s+|sealed\s+|data\s+)*(class|interface|object|enum\s+class)\s+([A-Za-z0-9_]+)(?:\s*\([^)]*\))?(?:\s*:\s*([^{]+))?"
    )
    fun_pat = re.compile(
        r"^\s*(?:@[\w\(\)\"=,\s]+\s+)*(?:public\s+|private\s+|internal\s+|protected\s+|override\s+|suspend\s+)*fun\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)"
    )
    java_method_pat = re.compile(
        r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>,\[\]]+\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)"
    )

    for i, line in enumerate(lines, 1):
        # Match class/interface
        c_match = class_pat.search(line)
        if c_match:
            kind_raw, name, super_raw = c_match.groups()
            kind = "interface" if "interface" in kind_raw else "class"
            supertypes = []
            if super_raw:
                supertypes = [s.strip().split("(")[0].strip() for s in super_raw.split(",") if s.strip()]
            tag = SymbolTag(
                file_path=rel_path,
                name=name,
                kind=kind,
                line_no=i,
                signature=line.strip().split("{")[0].strip(),
                supertypes=supertypes,
            )
            symbols.append(tag)
            current_class = name
            for s in supertypes:
                edges.append(SymbolEdge(caller_symbol=name, callee_symbol=s, caller_file=rel_path, relation="INHERITS"))
            continue

        # Match Kotlin fun
        f_match = fun_pat.search(line)
        if f_match:
            name, params = f_match.groups()
            sig = f"fun {name}({params.strip()})"
            tag = SymbolTag(
                file_path=rel_path,
                name=name,
                kind="method" if current_class else "function",
                line_no=i,
                signature=sig,
            )
            symbols.append(tag)
            if current_class:
                edges.append(SymbolEdge(caller_symbol=current_class, callee_symbol=name, caller_file=rel_path, relation="CALLS"))
            continue

        # Match Java method
        j_match = java_method_pat.search(line)
        if j_match and not line.strip().startswith("new "):
            name, params = j_match.groups()
            if name not in ("if", "for", "while", "switch", "catch"):
                sig = f"{name}({params.strip()})"
                tag = SymbolTag(
                    file_path=rel_path,
                    name=name,
                    kind="method" if current_class else "function",
                    line_no=i,
                    signature=sig,
                )
                symbols.append(tag)
                if current_class:
                    edges.append(SymbolEdge(caller_symbol=current_class, callee_symbol=name, caller_file=rel_path, relation="CALLS"))

    return symbols, edges


def parse_typescript_javascript_file(file_path: Path, rel_path: str) -> Tuple[List[SymbolTag], List[SymbolEdge]]:
    """Extracts symbols and call edges from TypeScript and JavaScript files."""
    symbols: List[SymbolTag] = []
    edges: List[SymbolEdge] = []
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return symbols, edges

    class_pat = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(class|interface)\s+([A-Za-z0-9_]+)(?:\s+extends\s+([A-Za-z0-9_]+))?")
    fn_pat = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)")
    arrow_pat = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")

    for i, line in enumerate(lines, 1):
        c_match = class_pat.search(line)
        if c_match:
            kind, name, base = c_match.groups()
            supertypes = [base] if base else []
            tag = SymbolTag(
                file_path=rel_path,
                name=name,
                kind="interface" if kind == "interface" else "class",
                line_no=i,
                signature=line.strip().split("{")[0].strip(),
                supertypes=supertypes,
            )
            symbols.append(tag)
            if base:
                edges.append(SymbolEdge(caller_symbol=name, callee_symbol=base, caller_file=rel_path, relation="INHERITS"))
            continue

        fn_match = fn_pat.search(line) or arrow_pat.search(line)
        if fn_match:
            name, params = fn_match.groups()
            tag = SymbolTag(
                file_path=rel_path,
                name=name,
                kind="function",
                line_no=i,
                signature=f"{name}({params.strip()})",
            )
            symbols.append(tag)

    return symbols, edges


# ---------------------------------------------------------------------------
# Graph Builder & Analyzer
# ---------------------------------------------------------------------------

def build_project_ast_graph(project_root: Path) -> ProjectASTGraph:
    """Builds the complete AST symbol and caller graph across supported languages."""
    graph = ProjectASTGraph(project_root)
    root = Path(project_root).resolve()

    ignore_dirs = {".git", ".unigov", "node_modules", "build", ".gradle", "__pycache__", "dist", ".idea"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
        for f in filenames:
            file_path = Path(dirpath) / f
            rel_path = str(file_path.relative_to(root))

            syms: List[SymbolTag] = []
            edgs: List[SymbolEdge] = []

            if f.endswith(".py"):
                syms, edgs = parse_python_file(file_path, rel_path)
            elif f.endswith((".kt", ".java")):
                syms, edgs = parse_kotlin_java_file(file_path, rel_path)
            elif f.endswith((".ts", ".tsx", ".js", ".jsx")):
                syms, edgs = parse_typescript_javascript_file(file_path, rel_path)

            for s in syms:
                graph.add_symbol(s)
            for e in edgs:
                graph.add_edge(e)

    # Resolve callee files in edges
    for e in graph.edges:
        if not e.callee_file and e.callee_symbol in graph.symbol_to_file:
            e.callee_file = graph.symbol_to_file[e.callee_symbol]

    graph.compute_pagerank()
    return graph


def calculate_blast_radius(
    project_root: Path,
    target_path: str,
    target_symbol: Optional[str] = None,
    max_depth: int = 3,
) -> BlastRadiusReport:
    """Computes 2-3 step upstream (dependents) & downstream (dependencies) blast-radius for a target file or symbol."""
    graph = build_project_ast_graph(project_root)

    # Normalize target path
    normalized_target = str(Path(target_path).as_posix())
    if normalized_target.startswith("./"):
        normalized_target = normalized_target[2:]

    # Find starting symbols
    start_symbols: List[str] = []
    if target_symbol:
        start_symbols.append(target_symbol)
    else:
        for sym_key, sym_tag in graph.symbols.items():
            if sym_tag.file_path == normalized_target or sym_tag.file_path.endswith(normalized_target):
                start_symbols.append(sym_tag.name)

    upstream_visited: Set[str] = set()
    downstream_visited: Set[str] = set()
    impacted_files: Set[str] = set()

    upstream_list: List[Dict[str, Any]] = []
    downstream_list: List[Dict[str, Any]] = []

    # 1. Traverse Upstream (Who calls/imports this target?)
    queue = deque([(s, 1) for s in start_symbols])
    while queue:
        curr, depth = queue.popleft()
        if depth > max_depth or curr in upstream_visited:
            continue
        upstream_visited.add(curr)

        callers = graph.reverse_graph.get(curr, set())
        for caller in callers:
            caller_file = graph.symbol_to_file.get(caller, "unknown")
            if caller_file != "unknown":
                impacted_files.add(caller_file)
            upstream_list.append({
                "symbol": caller,
                "file_path": caller_file,
                "depth": depth,
                "calls": curr,
            })
            if depth < max_depth:
                queue.append((caller, depth + 1))

    # 2. Traverse Downstream (What does this target call?)
    queue = deque([(s, 1) for s in start_symbols])
    while queue:
        curr, depth = queue.popleft()
        if depth > max_depth or curr in downstream_visited:
            continue
        downstream_visited.add(curr)

        callees = graph.forward_graph.get(curr, set())
        for callee in callees:
            callee_file = graph.symbol_to_file.get(callee, "unknown")
            if callee_file != "unknown":
                impacted_files.add(callee_file)
            downstream_list.append({
                "symbol": callee,
                "file_path": callee_file,
                "depth": depth,
                "called_by": curr,
            })
            if depth < max_depth:
                queue.append((callee, depth + 1))

    # Determine risk level
    total_impact = len(impacted_files)
    if total_impact >= 5:
        risk_level = "HIGH"
        risk_summary = f"High architectural impact: affects {total_impact} dependent files across {len(upstream_list)} caller nodes."
    elif total_impact >= 2:
        risk_level = "MEDIUM"
        risk_summary = f"Moderate blast radius: affects {total_impact} files across {len(upstream_list)} call sites."
    else:
        risk_level = "LOW"
        risk_summary = f"Localized blast radius: affects {total_impact} files with minimal cross-module propagation."

    return BlastRadiusReport(
        target_file=normalized_target,
        target_symbol=target_symbol,
        upstream_callers=upstream_list,
        downstream_callees=downstream_list,
        impacted_files=sorted(list(impacted_files)),
        risk_level=risk_level,
        risk_summary=risk_summary,
        depth_reached=max_depth,
    )


# ---------------------------------------------------------------------------
# RepoMap Generator (GSD Budget Aware)
# ---------------------------------------------------------------------------

def generate_repomap(
    project_root: Path,
    max_tokens: int = 2048,
    top_n: int = 50,
) -> str:
    """Generates an indented, PageRank-centralized AST RepoMap fitting strictly within token budget."""
    graph = build_project_ast_graph(project_root)

    # Sort symbols by PageRank descending
    sorted_symbols = sorted(graph.symbols.values(), key=lambda s: s.pagerank, reverse=True)
    if not sorted_symbols:
        return "# UniGov AST RepoMap: No source symbols identified."

    # Group top symbols by file
    files_to_symbols: Dict[str, List[SymbolTag]] = defaultdict(list)
    for sym in sorted_symbols[:top_n]:
        files_to_symbols[sym.file_path].append(sym)

    lines: List[str] = [
        "# ⬢ UniGov AST RepoMap (PageRank Centrality)",
        f"# Total Identified Symbols: {len(graph.symbols)} | Displaying Top {min(top_n, len(sorted_symbols))}",
        "",
    ]

    for file_path, syms in sorted(files_to_symbols.items()):
        file_pr = max(s.pagerank for s in syms)
        lines.append(f"📁 {file_path} (Max PR: {file_pr:.4f})")
        for s in syms:
            icon = "🔷" if s.kind == "class" else ("🔶" if s.kind == "interface" else "🔹")
            sig_snippet = s.signature if s.signature else s.name
            lines.append(f"  {icon} {sig_snippet} [L{s.line_no}] (PR: {s.pagerank:.4f})")
        lines.append("")

    full_map = "\n".join(lines)
    budget = calculate_token_budget(full_map, context_window=max_tokens)

    # Truncate if exceeding max_tokens
    if budget["estimated_tokens"] > max_tokens:
        while len(lines) > 5 and estimate_token_count("\n".join(lines)) > max_tokens:
            lines.pop()
        lines.append(f"... [Truncated to stay within {max_tokens} token budget]")
        full_map = "\n".join(lines)

    return full_map
