"""End-to-end tests operate on temporary project copies, never the test fixture repo."""
import hashlib
import json
import shutil
from pathlib import Path

from pseudotest.cli import main


SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_repo"


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _setup(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(SAMPLE, repo)
    output = tmp_path / "results"
    monkeypatch.chdir(repo)
    return repo, output


def _analyze(output, timeout=30):
    return main(["analyze", "--target", "src/calculator.py",
                 "--test-cmd", "python -m pytest tests/ -q",
                 "--timeout", str(timeout), "--output", str(output)])


def test_end_to_end_and_repository_unchanged(monkeypatch, tmp_path):
    repo, output = _setup(monkeypatch, tmp_path)
    before = _snapshot(repo)
    assert _analyze(output) == 0
    after = _snapshot(repo)
    assert before == after, "Original project was changed"
    report = json.loads((output / "results" / "analysis.json").read_text())
    f = {item["name"]: item for item in report["functions"]}
    assert f["discount"]["status"] == "PSEUDO_TESTED_CANDIDATE"
    assert [m["status"] for m in f["discount"]["mutants"]] == ["SURVIVED", "SURVIVED"]
    assert f["add"]["status"] == "DETECTED"
    assert f["total"]["status"] == "DETECTED"
    assert f["unused"]["status"] == "NOT_COVERED"
    indirect = "tests/test_calculator.py::test_total_indirectly_calls_add"
    assert indirect in f["add"]["dynamic_tests"]
    assert indirect in f["add"]["static_tests"]
    assert all(f["discount"]["return_type"] == "float" for _ in range(1))
    assert list(output.glob(".pseudotest-work-*")) == []


def test_skipped_related_test_makes_result_inconclusive(monkeypatch, tmp_path):
    repo, output = _setup(monkeypatch, tmp_path)
    tests = repo / "tests" / "test_calculator.py"
    tests.write_text(tests.read_text() + '''\

import pytest

@pytest.mark.skip(reason="demonstrate strict classification")
def test_discount_skipped():
    assert discount(100) == 90
''')
    assert _analyze(output) == 0
    report = json.loads((output / "results" / "analysis.json").read_text())
    discount = next(fn for fn in report["functions"] if fn["name"] == "discount")
    assert discount["status"] == "INCONCLUSIVE"
    assert discount["mutants"] == []


def test_mixed_return_types_are_unsupported(monkeypatch, tmp_path):
    repo, output = _setup(monkeypatch, tmp_path)
    target = repo / "src" / "calculator.py"
    target.write_text(target.read_text() + '''\

def mixed(flag):
    if flag:
        return 42
    return "different type"
''')
    tests = repo / "tests" / "test_calculator.py"
    tests.write_text(tests.read_text() + '''\

def test_mixed_int():
    from src.calculator import mixed
    assert mixed(True) == 42

def test_mixed_string():
    from src.calculator import mixed
    assert mixed(False) == "different type"
''')
    assert _analyze(output) == 0
    report = json.loads((output / "results" / "analysis.json").read_text())
    mixed = next(fn for fn in report["functions"] if fn["name"] == "mixed")
    assert mixed["status"] == "UNSUPPORTED"
    assert mixed["observed_types"] == ["int", "str"]
    assert mixed["mutants"] == []


def test_rejects_output_inside_project(monkeypatch, tmp_path, capsys):
    repo, _ = _setup(monkeypatch, tmp_path)
    assert main(["analyze", "--target", "src/calculator.py",
                 "--test-cmd", "pytest tests/", "--output", "./generated"]) == 2
    assert not (repo / "generated").exists()
    assert "outside" in capsys.readouterr().err


def test_fixture_setup_is_traced_as_related_test(monkeypatch, tmp_path):
    repo, output = _setup(monkeypatch, tmp_path)
    tests = repo / "tests" / "test_calculator.py"
    tests.write_text(tests.read_text() + '''\

import pytest

@pytest.fixture
def computed_total():
    return total(4, 5)

def test_total_via_fixture(computed_total):
    assert computed_total == 9
''')
    assert _analyze(output) == 0
    report = json.loads((output / "results" / "analysis.json").read_text())
    functions = {fn["name"]: fn for fn in report["functions"]}
    fixture_case = "tests/test_calculator.py::test_total_via_fixture"
    assert fixture_case in functions["total"]["dynamic_tests"]
    assert fixture_case in functions["add"]["dynamic_tests"]
    assert functions["total"]["status"] == "DETECTED"


def test_failing_baseline_stops_without_candidate_report(monkeypatch, tmp_path, capsys):
    repo, output = _setup(monkeypatch, tmp_path)
    tests = repo / "tests" / "test_calculator.py"
    tests.write_text(tests.read_text() + '''\

def test_broken_baseline():
    assert add(2, 3) == 99
''')
    assert _analyze(output) == 2
    assert not (output / "results" / "analysis.json").exists()
    assert "Baseline" in capsys.readouterr().err


def test_rejects_test_paths_outside_project(monkeypatch, tmp_path, capsys):
    repo, output = _setup(monkeypatch, tmp_path)
    outside = tmp_path / "external_tests"
    outside.mkdir()
    assert main(["analyze", "--target", "src/calculator.py",
                 "--test-cmd", f"pytest {outside} -q",
                 "--output", str(output)]) == 2
    assert "inside the current project" in capsys.readouterr().err
    assert not output.exists()


def test_mutant_timeout_is_inconclusive_and_workspace_removed(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "calc.py").write_text("def score(x):\n    return x + 10\n")
    (repo / "tests" / "test_calc.py").write_text('''\
import time
from src.calc import score

def test_score():
    result = score(2)
    if result == 0:
        time.sleep(20)
    assert result >= 0
''')
    output = tmp_path / "output"
    monkeypatch.chdir(repo)
    assert main(["analyze", "--target", "src/calc.py",
                 "--test-cmd", "python -m pytest tests/ -q", "--timeout", "4",
                 "--output", str(output)]) == 0
    report = json.loads((output / "results" / "analysis.json").read_text())
    score = report["functions"][0]
    assert score["status"] == "INCONCLUSIVE"
    assert [m["status"] for m in score["mutants"]] == ["TIMEOUT", "SURVIVED"]
    assert not list(output.glob(".pseudotest-work-*"))
