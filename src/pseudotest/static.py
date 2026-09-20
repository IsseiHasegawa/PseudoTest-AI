"""Conservative best-effort AST call graph: imports, aliases, direct and transitive calls.

Unknown dynamic dispatch is not fabricated as an edge. The baseline trace is
unioned with the graph by the coordinator.
"""
import ast
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
             ".pytest_cache", ".tox", ".nox", "node_modules", "build", "dist"}


def python_files(root: Path):
    for parent, directories, files in os.walk(root):
        directories[:] = sorted(d for d in directories
                                if d not in SKIP_DIRS and not (Path(parent) / d).is_symlink())
        for name in sorted(files):
            path = Path(parent) / name
            if name.endswith(".py") and not path.is_symlink():
                yield path


@dataclass
class Unit:
    file: str
    name: str
    node: ast.AST
    imports: dict[str, str]

    @property
    def key(self):
        return f"{self.file}::{self.name}"


def _modules(rel: str):
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    names = [".".join(parts)] if parts else []
    if parts and parts[0] == "src" and len(parts) > 1:
        names.append(".".join(parts[1:]))
    return [n for n in names if n]


def _imports(body, module):
    imports = {}
    for node in body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = (alias.name if alias.asname
                                                                       else alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            pkg = module.split(".")[:-1]
            if node.level:
                pkg = pkg[:max(0, len(pkg) - node.level + 1)]
            origin = ".".join(pkg + ([node.module] if node.module else [])) if node.level else (node.module or "")
            for alias in node.names:
                if alias.name != "*":
                    imports[alias.asname or alias.name] = f"{origin}.{alias.name}".strip(".")
    return imports


def _calls(node):
    """Skip nested definition bodies: they are not executed by an outer call."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Call):
            yield child.func
        yield from _calls(child)


def _dotted(expr):
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return (base + "." + expr.attr) if base else None
    return None


def static_related(root: Path, target_relative: str, target_names: set[str],
                   collected: list[str]) -> dict[str, set[str]]:
    trees = {}
    modules = defaultdict(set)
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            trees[rel] = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeError, OSError):
            continue
        for name in _modules(rel):
            modules[name].add(rel)
    units = {}
    top = defaultdict(dict)
    for rel, tree in trees.items():
        mod = _modules(rel)[0] if _modules(rel) else ""
        imports = _imports(tree.body, mod)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                unit = Unit(rel, node.name, node, {**imports, **_imports(node.body, mod)})
                units[unit.key] = unit
                top[rel][node.name] = unit.key
            elif isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        unit = Unit(rel, f"{node.name}.{method.name}", method,
                                    {**imports, **_imports(method.body, mod)})
                        units[unit.key] = unit
    def resolve(unit, expression):
        dotted = _dotted(expression)
        if not dotted:
            return set()
        prefix, _, rest = dotted.partition(".")
        candidates = set()
        if dotted in top[unit.file]:
            result = {top[unit.file][dotted]}
        else:
            result = set()
        mapped = unit.imports.get(prefix)
        if mapped:
            candidates.add(mapped + (("." + rest) if rest else ""))
        if "." in dotted:
            candidates.add(dotted)
        for candidate in candidates:
            module_name, sep, fn = candidate.rpartition(".")
            if not sep:
                continue
            files = modules.get(module_name, set())
            if len(files) == 1:
                file = next(iter(files))
                if fn in top[file]:
                    result.add(top[file][fn])
        return result

    graph = {}
    for key, unit in units.items():
        edges = set()
        for called in _calls(unit.node):
            edges.update(resolve(unit, called))
        graph[key] = edges

    targets = {top.get(target_relative, {}).get(n): n for n in target_names}
    targets.pop(None, None)
    mapping = {n: set() for n in target_names}
    for nodeid in collected:
        parts = nodeid.split("::")
        rel = parts[0].replace("\\", "/")
        if len(parts) < 2:
            continue
        names = [p.split("[")[0] for p in parts[1:]]
        test_key = f"{rel}::{'.'.join(names)}"
        if test_key not in graph:
            continue
        seen = set()
        todo = [test_key]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            todo.extend(graph.get(current, ()) - seen)
        for target_key, name in targets.items():
            if target_key in seen:
                mapping[name].add(nodeid)
    return mapping
