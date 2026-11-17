"""Unit tests for UniGov Ground-Truth AST Graph, Tree-Sitter RepoMap & Blast-Radius Engine."""

import sys
from pathlib import Path
from typer.testing import CliRunner

from unigov.ast_graph import (
    SymbolTag,
    SymbolEdge,
    ProjectASTGraph,
    parse_python_file,
    parse_kotlin_java_file,
    parse_typescript_javascript_file,
    build_project_ast_graph,
    calculate_blast_radius,
    generate_repomap,
)
from unigov.cli import app

runner = CliRunner()


def test_python_ast_extraction(tmp_path: Path):
    py_code = """
class BaseService:
    pass

class OrderService(BaseService):
    def process_order(self, order_id):
        return validate(order_id)

def validate(order_id):
    return True
"""
    py_file = tmp_path / "order_service.py"
    py_file.write_text(py_code, encoding="utf-8")

    syms, edges = parse_python_file(py_file, "order_service.py")
    sym_names = {s.name for s in syms}
    assert "BaseService" in sym_names
    assert "OrderService" in sym_names
    assert "process_order" in sym_names
    assert "validate" in sym_names

    # Check inheritance edge
    inherits_edges = [e for e in edges if e.relation == "INHERITS"]
    assert any(e.caller_symbol == "OrderService" and e.callee_symbol == "BaseService" for e in inherits_edges)

    # Check call edge
    call_edges = [e for e in edges if e.relation == "CALLS"]
    assert any(e.caller_symbol == "process_order" and e.callee_symbol == "validate" for e in call_edges)


def test_kotlin_ast_extraction(tmp_path: Path):
    kt_code = """package com.uniai.pos

interface PaymentProcessor {
    fun pay(amountPaise: Long): Boolean
}

data class UpiProcessor(val vpa: String) : PaymentProcessor {
    override fun pay(amountPaise: Long): Boolean {
        return executeUpi(vpa, amountPaise)
    }
}
"""
    kt_file = tmp_path / "UpiProcessor.kt"
    kt_file.write_text(kt_code, encoding="utf-8")

    syms, edges = parse_kotlin_java_file(kt_file, "UpiProcessor.kt")
    sym_names = {s.name for s in syms}
    assert "PaymentProcessor" in sym_names
    assert "UpiProcessor" in sym_names
    assert "pay" in sym_names

    # Check interface inheritance
    inherits_edges = [e for e in edges if e.relation == "INHERITS"]
    assert any(e.caller_symbol == "UpiProcessor" and e.callee_symbol == "PaymentProcessor" for e in inherits_edges)


def test_typescript_ast_extraction(tmp_path: Path):
    ts_code = """
export interface CartItem {
    id: string;
    pricePaise: number;
}

export class CartManager {
    calculateTotal(items: CartItem[]): number {
        return 100;
    }
}
"""
    ts_file = tmp_path / "cart.ts"
    ts_file.write_text(ts_code, encoding="utf-8")

    syms, edges = parse_typescript_javascript_file(ts_file, "cart.ts")
    sym_names = {s.name for s in syms}
    assert "CartItem" in sym_names
    assert "CartManager" in sym_names


def test_pagerank_computation(tmp_path: Path):
    graph = ProjectASTGraph(tmp_path)

    # Node A is called by B, C, D (High PageRank)
    graph.add_symbol(SymbolTag(file_path="a.py", name="CoreDb", kind="class", line_no=1))
    graph.add_symbol(SymbolTag(file_path="b.py", name="ServiceB", kind="class", line_no=1))
    graph.add_symbol(SymbolTag(file_path="c.py", name="ServiceC", kind="class", line_no=1))

    graph.add_edge(SymbolEdge(caller_symbol="ServiceB", callee_symbol="CoreDb", caller_file="b.py", callee_file="a.py"))
    graph.add_edge(SymbolEdge(caller_symbol="ServiceC", callee_symbol="CoreDb", caller_file="c.py", callee_file="a.py"))

    graph.compute_pagerank()

    pr_core = graph.symbols["a.py::CoreDb"].pagerank
    pr_b = graph.symbols["b.py::ServiceB"].pagerank

    assert pr_core > pr_b, f"CoreDb PR ({pr_core}) should be strictly greater than ServiceB PR ({pr_b})"


def test_blast_radius_multi_step(tmp_path: Path):
    # Setup chain: ModuleA calls ModuleB calls ModuleC
    (tmp_path / "mod_c.py").write_text("def base_calc():\n    return 10\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("from mod_c import base_calc\ndef mid_calc():\n    return base_calc()\n", encoding="utf-8")
    (tmp_path / "mod_a.py").write_text("from mod_b import mid_calc\ndef top_calc():\n    return mid_calc()\n", encoding="utf-8")

    report = calculate_blast_radius(tmp_path, "mod_c.py", target_symbol="base_calc", max_depth=3)
    assert report.target_file == "mod_c.py"
    assert report.target_symbol == "base_calc"

    # Upstream callers should reach mid_calc and top_calc
    caller_symbols = {u["symbol"] for u in report.upstream_callers}
    assert "mid_calc" in caller_symbols


def test_repomap_token_budget_generation(tmp_path: Path):
    (tmp_path / "sample.py").write_text("class TestApp:\n    def run(self): pass\n", encoding="utf-8")
    repomap = generate_repomap(tmp_path, max_tokens=500, top_n=10)
    assert "AST RepoMap" in repomap
    assert "TestApp" in repomap


def test_cli_repomap_and_blast_radius(tmp_path: Path):
    (tmp_path / "app.py").write_text("def start():\n    pass\n", encoding="utf-8")

    # CLI unigov repomap
    res_map = runner.invoke(app, ["repomap", "--dir", str(tmp_path)])
    assert res_map.exit_code == 0
    assert "AST RepoMap" in res_map.output

    # CLI unigov blast-radius
    res_br = runner.invoke(app, ["blast-radius", "app.py", "--dir", str(tmp_path)])
    assert res_br.exit_code == 0
    assert "Blast-Radius" in res_br.output
