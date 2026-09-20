"""Orchestrate baseline analysis and isolated mutation runs."""
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .functions import discover, mutant_source
from .model import AnalysisError, Config, DEFAULTS, FunctionResult
from .runner import copy_project, run_pytest, item_outcome, selected_status
from .static import static_related


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline_ok(run: dict) -> None:
    if run.get("status") != "COMPLETE":
        raise AnalysisError("Baseline pytest run failed: " + run.get("error", "unknown error")
                            + "\n" + run.get("stderr_tail", "")[-600:]
                            + "\n" + run.get("stdout_tail", "")[-600:])
    probe = run["probe"]
    if not probe.get("collected"):
        raise AnalysisError("Baseline pytest collected no tests")
    if run.get("returncode") not in (0, 1):
        raise AnalysisError(f"Baseline pytest had exit code {run.get('returncode')}")
    failures = [(test, item_outcome(probe.get("items", {}).get(test)))
                for test in probe["collected"]]
    if any(outcome not in {"PASS", "SKIPPED"} for _, outcome in failures):
        bad = [(n, s) for n, s in failures if s not in {"PASS", "SKIPPED"}]
        raise AnalysisError(f"Baseline tests must pass (skips allowed): {bad[:5]}")
    if run.get("returncode") != 0:
        raise AnalysisError("Baseline pytest failed; mutation results would be unreliable")


def analyze(config: Config) -> dict[str, Any]:
    relative = config.target.relative_to(config.root).as_posix()
    functions = discover(config.target, relative)
    original_text = config.target.read_text(encoding="utf-8")
    results = [FunctionResult(fn) for fn in functions]
    config.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pseudotest-work-", dir=config.output) as directory:
        workspace = Path(directory)
        pristine = workspace / "pristine"
        copy_project(config.root, pristine)
        baseline_copy = workspace / "baseline"
        copy_project(pristine, baseline_copy)
        baseline = run_pytest(config, baseline_copy, workspace / "baseline-probe.json")
        _baseline_ok(baseline)
        probe = baseline["probe"]
        collected = probe["collected"]
        eligible = {fn.name for fn in functions if fn.eligible}
        statics = static_related(pristine, relative, eligible, collected)
        for result in results:
            fn = result.function
            if not fn.eligible:
                result.status = "UNSUPPORTED"
                result.reason = fn.reason
                continue
            result.dynamic_tests = sorted(
                test for test in collected
                if probe.get("items", {}).get(test, {}).get("calls", {}).get(fn.name, 0))
            result.static_tests = sorted(statics.get(fn.name, set()))
            result.selected_tests = sorted(set(result.dynamic_tests) | set(result.static_tests))
            result.baseline_calls = sum(
                probe.get("items", {}).get(t, {}).get("calls", {}).get(fn.name, 0)
                for t in collected)
            types = set()
            for item in probe.get("items", {}).values():
                types.update(item.get("types", {}).get(fn.name, []))
            result.observed_types = sorted(types)
            if not result.baseline_calls:
                result.status = "NOT_COVERED"
                result.reason = "Target function was not executed in the baseline test run"
                continue
            baseline_selected = [item_outcome(probe.get("items", {}).get(t))
                                 for t in result.selected_tests]
            if any(status != "PASS" for status in baseline_selected):
                result.status = "INCONCLUSIVE"
                result.reason = "A related baseline test was skipped or did not pass"
                continue
            if len(types) != 1 or next(iter(types)) not in DEFAULTS:
                result.status = "UNSUPPORTED"
                result.reason = ("Observed return types are mixed, unknown or unsupported: "
                                 + (", ".join(sorted(types)) or "none"))
                continue
            result.return_type = next(iter(types))
            values = DEFAULTS[result.return_type]
            for index, value in enumerate(values, 1):
                try:
                    source, mutated_line = mutant_source(original_text, fn, value)
                except (AnalysisError, SyntaxError, ValueError, TypeError) as exc:
                    result.mutants.append({"index": index, "return_value": repr(value),
                                           "status": "ERROR", "reason": f"Mutation generation: {exc}"})
                    continue
                # Fresh copy for every mutant; no modified file or fixture output leaks
                # into the next mutation execution.
                mutant_copy = workspace / f"mutant-{fn.ordinal}-{index}"
                copy_project(pristine, mutant_copy)
                mutant_target = mutant_copy / relative
                mutant_target.write_text(source, encoding="utf-8")
                run = run_pytest(config, mutant_copy,
                                 workspace / f"probe-{fn.ordinal}-{index}.json",
                                 selected=result.selected_tests)
                status, reason, calls = selected_status(run, result.selected_tests, fn.name)
                # All executions must point to the actual mutated file, with a
                # code object whose first line matches the changed function.
                if status in {"SURVIVED", "KILLED"}:
                    matching = False
                    for t in result.selected_tests:
                        item = run.get("probe", {}).get("items", {}).get(t, {})
                        if item.get("calls", {}).get(fn.name, 0):
                            matching = True
                    if not matching or calls == 0:
                        status, reason = "NOT_EXECUTED", "Mutated function was not called"
                result.mutants.append({
                    "index": index, "return_value": repr(value), "status": status,
                    "reason": reason, "calls": calls,
                    "seconds": round(run.get("seconds", 0), 3),
                    "mutated_line": mutated_line,
                    "test_outcomes": {
                        t: item_outcome(run.get("probe", {}).get("items", {}).get(t))
                        for t in result.selected_tests
                    } if "probe" in run else {},
                })
            outcomes = [m["status"] for m in result.mutants]
            if outcomes == ["SURVIVED", "SURVIVED"]:
                result.status = "PSEUDO_TESTED_CANDIDATE"
                result.reason = "Both mutants survived all selected related tests"
            elif outcomes and len(outcomes) == 2 and all(x in {"SURVIVED", "KILLED"} for x in outcomes):
                result.status = "DETECTED" if outcomes == ["KILLED", "KILLED"] else "PARTIALLY_DETECTED"
                result.reason = "Both mutation runs completed with conclusive outcomes"
            else:
                result.status = "INCONCLUSIVE"
                result.reason = "A mutant was skipped, not executed, timed out or had an execution error"
    report = {
        "schema_version": 1,
        "tool_version": "0.2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(config.root),
        "target": relative,
        "target_sha256": sha256(config.target),
        "test_command": " ".join(config.pytest_args),
        "test_files_sha256": {
            p.relative_to(config.root).as_posix(): sha256(p)
            for p in sorted((config.root / "tests").rglob("*.py"))
            if (config.root / "tests").is_dir() and p.is_file()
        },
        "timeout_seconds": config.timeout,
        "baseline": {"tests_collected": len(collected), "seconds": round(baseline["seconds"], 3),
                     "status": "PASS", "skipped_tests": [
                         t for t in collected
                         if item_outcome(probe.get("items", {}).get(t)) == "SKIPPED"]},
        "functions": [r.as_dict() for r in results],
    }
    destination = config.output / "results"
    if destination.is_symlink():
        raise AnalysisError("Output results directory may not be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.resolve().is_relative_to(config.root):
        raise AnalysisError("Output results directory points inside the original project")
    path = destination / "analysis.json"
    temporary = destination / "analysis.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    report["report_path"] = str(path)
    return report
