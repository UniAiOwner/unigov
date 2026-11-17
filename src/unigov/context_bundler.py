"""1-Hop AST Context Bundler for Zero-Noise Task Execution in UniGov."""

import ast
import re
from pathlib import Path
from typing import List, Optional, Set
from .constants import normalize_posix_path, is_code_file


def extract_python_ast_signatures(code: str) -> str:
    """Extracts classes, dataclasses, and function signatures from Python code without full implementations."""
    try:
        tree = ast.parse(code)
    except Exception:
        return ""

    signatures: List[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_lines = [f"class {node.name}:"]
            doc = ast.get_docstring(node)
            if doc:
                class_lines.append(f'    """{doc}"""')
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                    args = [a.arg for a in item.args.args]
                    prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    class_lines.append(f"    {prefix}{item.name}({', '.join(args)}): ...")
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    class_lines.append(f"    {item.target.id}: ...")
            signatures.append("\n".join(class_lines))
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            args = [a.arg for a in node.args.args]
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            signatures.append(f"{prefix}{node.name}({', '.join(args)}): ...")

    return "\n\n".join(signatures)


def extract_curly_signatures(code: str, max_lines: int = 40) -> str:
    """Extracts interface, class, enum, and struct signatures from Kotlin, Java, TypeScript, and Go files."""
    lines = code.splitlines()
    extracted: List[str] = []
    capture = False
    open_brackets = 0

    decl_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:public\s+|private\s+|protected\s+|internal\s+)?(?:data\s+|sealed\s+|abstract\s+)?"
        r"(?:class|interface|enum|type|struct)\s+([A-Za-z0-9_]+)"
    )

    for line in lines:
        stripped = line.strip()
        if decl_pattern.search(line):
            capture = True
            extracted.append(line)
            open_brackets += line.count("{") - line.count("}")
            continue

        if capture:
            extracted.append(line)
            open_brackets += line.count("{") - line.count("}")
            if open_brackets <= 0:
                capture = False
                extracted.append("")  # blank separator

        if len(extracted) >= max_lines:
            extracted.append("... [additional declarations truncated]")
            break

    return "\n".join(extracted).strip()


def extract_file_signatures(path: Path) -> str:
    """Extracts high-level signatures according to file type."""
    if not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    if path.suffix == ".py":
        sigs = extract_python_ast_signatures(content)
        return sigs if sigs else content[:800]
    else:
        sigs = extract_curly_signatures(content)
        return sigs if sigs else content[:800]


def find_one_hop_dependency_paths(root_dir: Path, target_file: Path) -> List[Path]:
    """Finds directly imported local workspace files for a given target file."""
    if not target_file.is_file():
        return []

    try:
        content = target_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    dependencies: List[Path] = []
    seen: Set[Path] = set()

    if target_file.suffix == ".py":
        # Extract relative and local absolute imports
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("from .") or line.startswith("import ."):
                m = re.match(r"(?:from|import)\s+\.*([A-Za-z0-9_]+)", line)
                if m:
                    mod_name = m.group(1)
                    cand = target_file.parent / f"{mod_name}.py"
                    if cand.is_file() and cand.resolve() not in seen:
                        dependencies.append(cand)
                        seen.add(cand.resolve())
            elif line.startswith("from ") or line.startswith("import "):
                m = re.match(r"(?:from|import)\s+([A-Za-z0-9_]+)", line)
                if m:
                    mod_name = m.group(1)
                    for cand in target_file.parent.glob(f"{mod_name}.py"):
                        if cand.is_file() and cand.resolve() not in seen:
                            dependencies.append(cand)
                            seen.add(cand.resolve())

    elif target_file.suffix in {".kt", ".java"}:
        # Extract package and relative domain imports
        package_m = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)", content, re.MULTILINE)
        base_pkg = package_m.group(1) if package_m else ""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("import ") and base_pkg and base_pkg in line:
                m = re.match(r"import\s+([a-zA-Z0-9_.]+)", line)
                if m:
                    full_class = m.group(1)
                    class_name = full_class.split(".")[-1]
                    for cand in root_dir.rglob(f"{class_name}.*"):
                        if cand.is_file() and cand.resolve() not in seen and is_code_file(cand):
                            dependencies.append(cand)
                            seen.add(cand.resolve())
                            break

    elif target_file.suffix in {".ts", ".tsx", ".js"}:
        # Extract relative JS/TS imports
        for line in content.splitlines():
            line = line.strip()
            m = re.search(r"""(?:from|import)\s+['"](\.[^'"]+)['"]""", line)
            if m:
                rel = m.group(1)
                for ext in [".ts", ".tsx", ".js", "/index.ts", "/index.tsx"]:
                    cand = (target_file.parent / rel).with_suffix(ext) if not ext.startswith("/") else (target_file.parent / rel / "index.ts")
                    if cand.is_file() and cand.resolve() not in seen:
                        dependencies.append(cand)
                        seen.add(cand.resolve())
                        break

    return dependencies[:4]


def bundle_one_hop_context(root_dir: Path, target_files: List[str], max_chars: int = 4000) -> str:
    """Bundles signatures of 1-hop dependencies for target files into a markdown prompt block."""
    norm_targets = {normalize_posix_path(f) for f in target_files}
    discovered_deps: List[Path] = []
    seen_deps: Set[Path] = set()

    for tf in target_files:
        norm = normalize_posix_path(tf)
        p = root_dir / norm
        if not p.is_file():
            continue
        deps = find_one_hop_dependency_paths(root_dir, p)
        for d in deps:
            d_norm = normalize_posix_path(d.relative_to(root_dir) if d.is_relative_to(root_dir) else d)
            if d_norm not in norm_targets and d.resolve() not in seen_deps:
                discovered_deps.append(d)
                seen_deps.add(d.resolve())

    if not discovered_deps:
        return ""

    blocks: List[str] = [
        "\n### 🔗 1-HOP DEPENDENCY INTERFACES & CONTRACTS (ZERO-NOISE CONTEXT):"
    ]
    char_count = 0

    for dep in discovered_deps:
        rel = dep.relative_to(root_dir) if dep.is_relative_to(root_dir) else dep
        sigs = extract_file_signatures(dep)
        if not sigs:
            continue
        entry = f"\n**Reference:** `{normalize_posix_path(rel)}`\n```{dep.suffix.lstrip('.')}\n{sigs}\n```\n"
        if char_count + len(entry) > max_chars:
            blocks.append("\n... [further dependency signatures omitted]")
            break
        blocks.append(entry)
        char_count += len(entry)

    return "\n".join(blocks) if len(blocks) > 1 else ""


def estimate_token_count(text: str) -> int:
    """Estimates the token count of a given text or code string (1 token ~ 3.8 chars)."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        # High-accuracy fallback heuristic for code & markdown
        clean_len = len(text.strip())
        return max(1, int(clean_len / 3.85))


def calculate_token_budget(bundled_prompt: str, context_window: int = 200_000) -> dict:
    """Calculates context-rot budget metrics and enforces the GSD 0-30% sweet spot."""
    tokens = estimate_token_count(bundled_prompt)
    utilization_pct = round((tokens / max(context_window, 1)) * 100, 2)

    if utilization_pct <= 30.0:
        zone = "SWEET_SPOT"
        status_label = "🟢 Sweet Spot (Optimal Cognitive Precision)"
        recommendation = "Safe to proceed with task execution. Cognitive reasoning is 100% sharp."
    elif utilization_pct <= 50.0:
        zone = "CAUTION"
        status_label = "🟡 Caution Zone (Moderate Context Load)"
        recommendation = "Approaching context saturation. Limit additional files or prepare to compact."
    else:
        zone = "ROT_DANGER"
        status_label = "🔴 Context Rot Alert (High Drift Risk)"
        recommendation = "Context exceeds 50% capacity! Spawning a fresh sub-agent context window is strongly advised."

    return {
        "estimated_tokens": tokens,
        "context_window": context_window,
        "utilization_pct": utilization_pct,
        "zone": zone,
        "status_label": status_label,
        "recommendation": recommendation,
    }


def render_budget_badge(budget: dict) -> str:
    """Renders a single-line terminal badge for prompt headers and companion status."""
    pct = budget["utilization_pct"]
    tokens = budget["estimated_tokens"]
    zone = budget["zone"]
    if zone == "SWEET_SPOT":
        return f"[green]⬢ Context: {tokens} tok ({pct}%) [SWEET SPOT][/green]"
    elif zone == "CAUTION":
        return f"[yellow]⚠️ Context: {tokens} tok ({pct}%) [CAUTION][/yellow]"
    else:
        return f"[bold red]🚨 Context: {tokens} tok ({pct}%) [ROT DANGER][/bold red]"

