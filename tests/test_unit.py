"""Fast unit tests of the selection, mutation and classification invariants."""
from pathlib import Path
import ast
import json

import pytest

from pseudotest.functions import discover, mutant_source
from pseudotest.model import AnalysisError, Function
from pseudotest.runner import parse_test_cmd, item_outcome, selected_status
from pseudotest.static import static_related


def test_discover_excludes_special_and_duplicate_functions(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text('''\
def ordinary(x):
    return x

@decorator
def decorated():
    return 1

def duplicated():
    return 1

def duplicated():
    return 2

def generated():
    yield 2

async def coroutine():
    return 4
''')
    functions = discover(target, "mod.py")
    assert [f.name for f in functions if f.eligible] == ["ordinary"]
    assert any(f.name == "generated" and "Generator" in f.reason for f in functions)


def test_mutation_only_changes_target_definition():
    source = '''\
def first(a):
    return a * 2

def second(a):
    return a + 1
'''
    fn = Function("mod.py", "first", 1, 0)
    mutated, line = mutant_source(source, fn, 0)
    tree = ast.parse(mutated)
    assert line == 1
    assert ast.unparse(tree.body[0].body[0]) == "return 0"
    assert ast.unparse(tree.body[1].body[0]) == "return a + 1"
    with pytest.raises(AnalysisError):
        mutant_source(source, Function("mod.py", "first", 5, 0), 0)


def test_static_transitive_calls_aliases_and_parameterized_test(tmp_path):
    root = tmp_path
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text('''\
def inner():
    return 5

def middle():
    return inner()
''')
    (root / "tests" / "test_calc.py").write_text('''\
from src.calc import middle as calculation

def test_nested():
    assert calculation() == 5

def test_other():
    assert True
''')
    ids = ["tests/test_calc.py::test_nested[case0]", "tests/test_calc.py::test_other"]
    mapping = static_related(root, "src/calc.py", {"inner", "middle"}, ids)
    assert mapping["inner"] == {ids[0]}
    assert mapping["middle"] == {ids[0]}


def test_command_safety_and_subset_contract():
    assert parse_test_cmd('python -m pytest tests/ -q') == ["tests/", "-q"]
    assert parse_test_cmd('pytest tests/test_mod.py -vv') == ["tests/test_mod.py", "-vv"]
    for command in ["bash -c 'rm -rf something'", "pytest tests/ -n 4",
                    "pytest tests/ --cov=src", "pytest -q", "python other.py"]:
        with pytest.raises(AnalysisError):
            parse_test_cmd(command)


def _run(item, status="COMPLETE"):
    return {"status": status, "returncode": 1 if item.get("phases", {}).get("call", {}).get("outcome") == "failed" else 0,
            "probe": {"collected": ["tests/test.py::test_fn"],
            "items": {"tests/test.py::test_fn": item}, "foreign_calls": 0}}


def _item(phase="passed", calls=1):
    return {"phases": {"setup": {"outcome": "passed"},
                       "call": {"outcome": phase},
                       "teardown": {"outcome": "passed"}},
            "calls": {"fn": calls}}


def test_conservative_selected_status():
    selected = ["tests/test.py::test_fn"]
    assert selected_status(_run(_item()), selected, "fn")[0] == "SURVIVED"
    assert selected_status(_run(_item("failed")), selected, "fn")[0] == "KILLED"
    assert selected_status(_run(_item(calls=0)), selected, "fn")[0] == "NOT_EXECUTED"
    bad = _item()
    bad["phases"]["call"] = {"outcome": "skipped"}
    assert selected_status(_run(bad), selected, "fn")[0] == "SKIPPED"
    bad = _item()
    bad["phases"]["setup"] = {"outcome": "failed"}
    assert selected_status(_run(bad), selected, "fn")[0] == "ERROR"
    assert selected_status({"status": "TIMEOUT", "error": "time"}, selected, "fn")[0] == "TIMEOUT"
    assert item_outcome(None) == "ERROR"
