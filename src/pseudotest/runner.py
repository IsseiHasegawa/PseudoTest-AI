"""Run pytest in clean copies of the project with per-item profiling."""
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .model import AnalysisError, Config
from .static import SKIP_DIRS

# The CLI deliberately supports only ordinary pytest paths/nodeids plus passive
# display flags. Arbitrary shell commands, plugins, filters and parallelism are
# not yet supported; they can invalidate node-ID selection or repository safety.
DISPLAY_FLAGS = {"-q", "-qq", "-v", "-vv", "-s", "-ra", "-rA", "--disable-warnings",
                 "--strict-markers", "--strict-config", "--no-header", "--no-summary"}


def parse_test_cmd(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise AnalysisError(f"Malformed --test-cmd: {exc}") from exc
    if not parts:
        raise AnalysisError("--test-cmd is empty")
    executable = Path(parts[0]).name.lower()
    if executable in {"pytest", "py.test"}:
        args = parts[1:]
    elif executable.startswith("python") or Path(parts[0]).resolve() == Path(sys.executable).resolve():
        if parts[1:3] != ["-m", "pytest"]:
            raise AnalysisError("--test-cmd must invoke python -m pytest or pytest")
        args = parts[3:]
    else:
        raise AnalysisError("--test-cmd supports pytest only, not shell commands")
    if not args:
        raise AnalysisError("Specify a test path in --test-cmd (e.g. 'python -m pytest tests/ -q')")
    for arg in args:
        if arg.startswith("-") and arg not in DISPLAY_FLAGS and not arg.startswith(("--tb=", "--color=")):
            raise AnalysisError(f"Unsupported pytest option {arg!r}; use simple test paths and display flags")
        if arg.startswith("--tb=") and arg[5:] not in {"short", "line", "auto", "no", "long", "native"}:
            raise AnalysisError("Invalid --tb value")
        if arg.startswith("--color=") and arg[8:] not in {"yes", "no", "auto"}:
            raise AnalysisError("Invalid --color value")
    if not any(not a.startswith("-") for a in args):
        raise AnalysisError("Specify at least one test path in --test-cmd")
    return args


def copy_project(origin: Path, destination: Path) -> None:
    def ignore(parent, names):
        return {name for name in names if name in SKIP_DIRS or name.endswith((".pyc", ".pyo"))
                or (Path(parent) / name).is_symlink()}
    shutil.copytree(origin, destination, ignore=ignore, symlinks=False)


def run_pytest(config: Config, project_copy: Path, report_file: Path,
               selected: list[str] | None = None, target_copy_line: int | None = None) -> dict:
    relative = config.target.relative_to(config.root)
    target_copy = project_copy / relative
    if not target_copy.exists():
        return {"status": "ERROR", "error": "Target missing from project copy"}
    args = config.pytest_args if selected is None else (
        [part for part in config.pytest_args if part.startswith("-")] + selected)
    argv = [sys.executable, "-m", "pytest", "-p", "pseudotest._pytest_plugin",
            "-p", "no:cacheprovider", "-o", "addopts=", *args]
    env = os.environ.copy()
    package_src = str(config.package_src)
    # Do not carry PYTHONPATH entries that resolve into the original project.
    old_paths = []
    for entry in env.get("PYTHONPATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).resolve().is_relative_to(config.root):
                continue
        except (OSError, ValueError):
            continue
        old_paths.append(entry)
    env["PYTHONPATH"] = os.pathsep.join([str(project_copy), str(project_copy / "src"),
                                          package_src, *old_paths])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Do not let globally configured pytest options override scoped selection.
    env.pop("PYTEST_ADDOPTS", None)
    env["PSEUDOTEST_TARGET_COPY"] = str(target_copy)
    env["PSEUDOTEST_TARGET_ORIGINAL"] = str(config.target)
    env["PSEUDOTEST_PROBE_REPORT"] = str(report_file)
    # Keep OS temp files and many pytest fixtures' temp artifacts outside repo.
    env["TMPDIR"] = str(project_copy.parent)
    started = time.monotonic()
    try:
        # A new process session lets timeout cleanup terminate the whole pytest
        # process group on POSIX, not just its immediate Python process.
        process = subprocess.Popen(
            argv, cwd=project_copy, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return {"status": "ERROR", "error": str(exc)}
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=config.timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.communicate()
        return {"status": "TIMEOUT", "seconds": time.monotonic() - started,
                "error": f"pytest exceeded {config.timeout:g} seconds"}
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    result = {"status": "COMPLETE", "seconds": time.monotonic() - started,
              "returncode": process.returncode,
              "stdout_tail": stdout[-1500:], "stderr_tail": stderr[-1500:]}
    if not report_file.is_file():
        result.update(status="ERROR", error="pytest instrumentation did not produce a report")
        return result
    try:
        probe = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result.update(status="ERROR", error=f"Invalid pytest instrumentation result: {exc}")
        return result
    result["probe"] = probe
    if probe.get("foreign_calls"):
        result.update(status="ERROR", error="Original project code was imported instead of the copy")
    elif probe.get("collection_error") or process.returncode in {2, 3, 4, 5}:
        result.update(status="ERROR", error="pytest collection, setup or configuration failed")
    return result


def item_outcome(item: dict | None) -> str:
    if item is None:
        return "ERROR"
    phases = item.get("phases", {})
    if not phases:
        return "ERROR"
    if any(p.get("outcome") == "skipped" for p in phases.values()):
        return "SKIPPED"
    if "call" not in phases:
        return "ERROR"
    if any(phases.get(when, {}).get("outcome") == "failed"
           for when in ("setup", "teardown")):
        return "ERROR"
    call = phases["call"].get("outcome")
    return "PASS" if call == "passed" else ("FAIL" if call == "failed" else "ERROR")


def selected_status(run: dict, selected: list[str], function_name: str) -> tuple[str, str, int]:
    if run.get("status") != "COMPLETE":
        return run.get("status", "ERROR"), run.get("error", "pytest execution error"), 0
    probe = run["probe"]
    if probe.get("foreign_calls"):
        return "ERROR", "Original repository module was imported", 0
    if not selected:
        return "NOT_EXECUTED", "No related tests selected", 0
    collected = set(probe.get("collected", []))
    if any(node not in collected for node in selected):
        return "ERROR", "Selected pytest node ID is missing from the collected suite", 0
    total_calls = 0
    outcomes = []
    for nodeid in selected:
        item = probe.get("items", {}).get(nodeid)
        outcomes.append(item_outcome(item))
        if item:
            total_calls += item.get("calls", {}).get(function_name, 0)
    if "SKIPPED" in outcomes:
        return "SKIPPED", "At least one related test was skipped", total_calls
    if "ERROR" in outcomes:
        return "ERROR", "A selected test had a setup, teardown or execution error", total_calls
    if not total_calls:
        return "NOT_EXECUTED", "The mutant was never executed by selected tests", 0
    if run.get("returncode") not in (0, 1):
        return "ERROR", "pytest returned an unexpected exit code", total_calls
    if "FAIL" in outcomes:
        return "KILLED", "A related test failed after executing the mutant", total_calls
    if all(state == "PASS" for state in outcomes):
        if run.get("returncode", 0) != 0:
            return "ERROR", "pytest exited unsuccessfully despite passing selected tests", total_calls
        return "SURVIVED", "All related tests passed after executing the mutant", total_calls
    return "ERROR", "Incomplete pytest result", total_calls
