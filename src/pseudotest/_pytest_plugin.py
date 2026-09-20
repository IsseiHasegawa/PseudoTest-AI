"""Loaded by pytest in a child process; serialize test-scoped function traces.

Set environment variables from the parent runner. No modifications are made
inside the target repository: the whole test run is inside a workspace copy.
"""
import ast
import json
import os
from pathlib import Path
import sys

import pytest


class Probe:
    def __init__(self):
        self.path = Path(os.environ["PSEUDOTEST_TARGET_COPY"]).resolve()
        self.original = Path(os.environ["PSEUDOTEST_TARGET_ORIGINAL"]).resolve()
        self.report = Path(os.environ["PSEUDOTEST_PROBE_REPORT"])
        tree = ast.parse(self.path.read_text(encoding="utf-8"))
        self.by_line = {n.lineno: n.name for n in tree.body if isinstance(n, ast.FunctionDef)
                        and not n.decorator_list}
        self.by_name = set(self.by_line.values())
        self.items = {}
        self.collected = []
        self.current = None
        self.foreign_calls = 0
        self.usage = {}
        self.collection_error = False

    def profile(self, frame, event, arg):
        if event not in {"call", "return"}:
            return
        code = frame.f_code
        if code.co_name not in self.by_name:
            return
        try:
            filename = Path(code.co_filename).resolve()
        except (OSError, ValueError):
            return
        if filename == self.original and self.original != self.path:
            if event == "call":
                self.foreign_calls += 1
            return
        if filename != self.path:
            return
        name = self.by_line.get(code.co_firstlineno)
        if name != code.co_name:
            return
        if self.current is None:
            return
        data = self.items.setdefault(self.current, {"calls": {}, "types": {}, "phases": {}})
        if event == "call":
            data["calls"][name] = data["calls"].get(name, 0) + 1
        elif event == "return":
            result_type = type(arg).__name__
            values = data["types"].setdefault(name, [])
            if result_type not in values:
                values.append(result_type)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        self.current = item.nodeid
        self.items.setdefault(self.current, {"calls": {}, "types": {}, "phases": {}})
        previous = sys.getprofile()
        sys.setprofile(self.profile)
        try:
            yield
        finally:
            sys.setprofile(previous)
            self.current = None

    def pytest_collection_modifyitems(self, items):
        self.collected = [item.nodeid for item in items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_error = True

    def pytest_runtest_logreport(self, report):
        result = self.items.setdefault(report.nodeid, {"calls": {}, "types": {}, "phases": {}})
        result["phases"][report.when] = {
            "outcome": report.outcome,
            "error": str(report.longrepr)[-1200:] if report.failed else "",
        }

    def pytest_sessionfinish(self, session, exitstatus):
        data = {"collected": self.collected, "items": self.items,
                "foreign_calls": self.foreign_calls,
                "collection_error": self.collection_error,
                "exitstatus": int(exitstatus)}
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pytest_configure(config):
    if os.environ.get("PSEUDOTEST_PROBE_REPORT"):
        config.pluginmanager.register(Probe(), name="pseudotest-trace-probe")
