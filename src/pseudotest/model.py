"""Data model shared by analyzers, execution, and reporting."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, tuple[object, object]] = {
    "bool": (False, True),
    "int": (0, 1),
    "float": (0.0, 1.0),
    "str": ("", "mutant"),
}

@dataclass
class Function:
    path: str
    name: str
    line: int
    ordinal: int
    eligible: bool = True
    reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.path}:{self.name}:{self.line}"

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.key, "name": self.name, "path": self.path,
                "line": self.line, "ordinal": self.ordinal}

@dataclass
class Config:
    root: Path
    target: Path
    output: Path
    pytest_args: list[str]
    timeout: float
    package_src: Path

@dataclass
class AnalysisError(Exception):
    message: str
    def __str__(self) -> str:
        return self.message

@dataclass
class FunctionResult:
    function: Function
    status: str = "INCONCLUSIVE"
    reason: str = ""
    return_type: str | None = None
    observed_types: list[str] = field(default_factory=list)
    dynamic_tests: list[str] = field(default_factory=list)
    static_tests: list[str] = field(default_factory=list)
    selected_tests: list[str] = field(default_factory=list)
    baseline_calls: int = 0
    mutants: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {**self.function.as_dict(), "status": self.status, "reason": self.reason,
                "return_type": self.return_type, "observed_types": self.observed_types,
                "dynamic_tests": self.dynamic_tests, "static_tests": self.static_tests,
                "selected_tests": self.selected_tests, "baseline_calls": self.baseline_calls,
                "mutants": self.mutants}
