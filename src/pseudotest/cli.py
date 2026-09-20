"""Command line entry point for phase-one analysis."""
import argparse
import math
import sys
from pathlib import Path
from .analysis import analyze
from .model import AnalysisError, Config
from .runner import parse_test_cmd
from .improve import improve
from .nemotron import DEFAULT_MODEL


def _config(arguments: argparse.Namespace) -> Config:
    root = Path.cwd().resolve()
    target = (root / arguments.target).resolve()
    if not target.is_file() or target.suffix != ".py" or not target.is_relative_to(root):
        raise AnalysisError("--target must be an existing .py file inside the current project")
    output = (root / arguments.output).resolve() if arguments.output else (
        root.parent / f"{root.name}-pseudotest-output").resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise AnalysisError("--output must be outside the target project, not its ancestor")
    if output.exists() and not output.is_dir():
        raise AnalysisError("--output must be a directory")
    if not math.isfinite(arguments.timeout) or arguments.timeout <= 0:
        raise AnalysisError("--timeout must be positive")
    args = parse_test_cmd(arguments.test_cmd)
    normalized = []
    for arg in args:
        if arg.startswith("-"):
            normalized.append(arg)
            continue
        path_part, marker, node_suffix = arg.partition("::")
        test_path = (root / path_part).resolve()
        if not test_path.is_relative_to(root) or not test_path.exists():
            raise AnalysisError("--test-cmd paths must exist inside the current project")
        normalized.append(test_path.relative_to(root).as_posix() +
                          (("::" + node_suffix) if marker else ""))
    return Config(root, target, output, normalized, arguments.timeout,
                  Path(__file__).resolve().parent.parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pseudotest", description="Hybrid function-level extreme mutation testing")
    subcommands = parser.add_subparsers(dest="action", required=True)
    analysis = subcommands.add_parser("analyze", help="Analyze one Python file (no AI/API calls)")
    analysis.add_argument("--target", required=True, help="Target .py path, relative to current project root")
    analysis.add_argument("--test-cmd", required=True, help='E.g. "python -m pytest tests/ -q"')
    analysis.add_argument("--output", help="Output directory outside the project (default: sibling folder)")
    analysis.add_argument("--timeout", type=float, default=60.0, help="Seconds per pytest invocation (default 60)")
    improvement = subcommands.add_parser("improve", help="Generate and validate Nemotron tests from an existing analysis report")
    improvement.add_argument("--report", required=True, help="Phase 1 results/analysis.json")
    improvement.add_argument("--output", help="Dedicated output directory outside the target repo")
    improvement.add_argument("--timeout", type=float, help="Seconds per validation pytest run; defaults to report value")
    improvement.add_argument("--api-timeout", type=float, default=90, help="Seconds per Nemotron API call")
    improvement.add_argument("--model", default=DEFAULT_MODEL, help="NVIDIA model ID from build.nvidia.com")
    improvement.add_argument("--max-attempts", type=int, default=3, help="Max generations per function, 1-10")
    args = parser.parse_args(argv)
    if args.action == "improve":
        try:
            result = improve(Path(args.report),
                             output=Path(args.output) if args.output else None,
                             timeout=args.timeout, api_timeout=args.api_timeout,
                             model=args.model, max_attempts=args.max_attempts)
        except (AnalysisError, OSError, ValueError, KeyError) as exc:
            print(f"PseudoTest AI error: {exc}", file=sys.stderr)
            return 2
        improved = [fn for fn in result["functions"] if fn["status"] == "IMPROVED"]
        print(f"Nemotron improvement: {len(improved)}/{len(result['functions'])} functions improved")
        for fn in result["functions"]:
            print(f"  {fn['name']}(): {fn['status']} ({len(fn['attempts'])} attempts)")
            if fn['generated_test']:
                print(f"    Verified test: {fn['generated_test']}")
        print(f"Improvement report: {result['report_path']}")
        return 0 if len(improved) == len(result['functions']) else 1
    try:
        config = _config(args)
        print(f"PseudoTest AI  |  target: {config.target.relative_to(config.root)}", flush=True)
        print("Running baseline, hybrid relevance analysis and isolated mutants...", flush=True)
        result = analyze(config)
    except (AnalysisError, PermissionError, OSError) as exc:
        print(f"PseudoTest AI error: {exc}", file=sys.stderr)
        return 2
    groups = {}
    for fn in result["functions"]:
        groups[fn["status"]] = groups.get(fn["status"], 0) + 1
    print(f"\nBaseline: {result['baseline']['tests_collected']} tests; "
          f"{result['baseline']['seconds']:.3f} s")
    print("Functions: " + ", ".join(f"{key}={count}" for key, count in sorted(groups.items())))
    candidates = [f for f in result["functions"] if f["status"] == "PSEUDO_TESTED_CANDIDATE"]
    total_functions = len(result["functions"])
    if total_functions:
        pt_rate = len(candidates) / total_functions * 100
        print(f"PT candidate rate: {len(candidates)}/{total_functions} ({pt_rate:.1f}%)")
    else:
        print("PT candidate rate: N/A (no target functions)")
    print(f"\nPSEUDO-TESTED CANDIDATES ({len(candidates)})")
    for fn in candidates:
        print(f"  {fn['name']}()  {fn['path']}:{fn['line']}  related tests={len(fn['selected_tests'])}")
        for mutant in fn["mutants"]:
            print(f"    return {mutant['return_value']}: {mutant['status']}")
    if not candidates:
        print("  None under the selected tests and two-mutant criterion.")
    uncertain = [f for f in result["functions"] if f["status"] in
                 {"INCONCLUSIVE", "NOT_COVERED", "UNSUPPORTED"}]
    if uncertain:
        print(f"\nNOT EVALUATED / INCONCLUSIVE ({len(uncertain)})")
        for fn in uncertain:
            print(f"  {fn['name']}()  {fn['status']}: {fn['reason']}")
    print(f"\nJSON report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
