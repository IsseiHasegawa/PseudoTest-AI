"""Discover and mutate top-level, undecorated synchronous Python functions."""
import ast
from collections import Counter
from pathlib import Path
from .model import Function, AnalysisError, DEFAULTS


def _generator(node: ast.FunctionDef) -> bool:
    # Nested definitions do not turn the enclosing function into a generator.
    def contains_yield(value: ast.AST) -> bool:
        if isinstance(value, (ast.Yield, ast.YieldFrom, ast.Await)):
            return True
        if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return False
        return any(contains_yield(child) for child in ast.iter_child_nodes(value))
    return any(contains_yield(stmt) for stmt in node.body)


def discover(path: Path, relative: str) -> list[Function]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError, OSError) as exc:
        raise AnalysisError(f"Cannot parse target: {exc}") from exc
    counts = Counter(n.name for n in tree.body if isinstance(n, ast.FunctionDef))
    functions = []
    for ordinal, node in enumerate(n for n in tree.body if isinstance(n, ast.FunctionDef)):
        reason = ""
        if node.decorator_list:
            reason = "Decorated function is outside initial support"
        elif counts[node.name] != 1:
            reason = "Duplicate top-level function name"
        elif _generator(node):
            reason = "Generator / await expression is outside initial support"
        elif node.name.startswith("test_") and relative.startswith("tests/"):
            reason = "Test function"
        functions.append(Function(relative, node.name, node.lineno, ordinal,
                                  eligible=not reason, reason=reason))
    return functions


def mutant_source(original: str, function: Function, value: object) -> tuple[str, int]:
    """Change exactly the specified top-level function in a *copy* of a module.

    AST unparse preserves executable semantics in conventional Python but not
    comments or layout. Never write this output into the user's original tree.
    """
    tree = ast.parse(original)
    top = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if function.ordinal >= len(top) or (top[function.ordinal].name != function.name
                                         or top[function.ordinal].lineno != function.line):
        raise AnalysisError(f"Target function changed: {function.key}")
    node = top[function.ordinal]
    node.body = [ast.Return(value=ast.Constant(value=value))]
    ast.fix_missing_locations(tree)
    rendered = ast.unparse(tree) + "\n"
    changed = ast.parse(rendered)
    updated = [n for n in changed.body if isinstance(n, ast.FunctionDef)][function.ordinal]
    if type(value).__name__ not in DEFAULTS:
        raise AnalysisError("Unsupported mutant return value")
    return rendered, updated.lineno
