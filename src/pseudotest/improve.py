"""Separate report-driven Nemotron test-generation and mutation validation phase."""
import ast
import hashlib
import json
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .functions import discover, mutant_source
from .model import AnalysisError, Config, DEFAULTS
from .nemotron import create_test, DEFAULT_MODEL
from .runner import copy_project, run_pytest, item_outcome


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outside(root: Path, output: Path) -> None:
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise AnalysisError('--output must be outside the target repo, not its ancestor')
    if output.exists() and not output.is_dir():
        raise AnalysisError('--output must be a directory')


def _load_report(report_path: Path, output_path: Path | None, timeout: float | None):
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AnalysisError(f'Cannot read analysis report: {exc}') from exc
    if report.get('schema_version') != 1 or report.get('baseline', {}).get('status') != 'PASS':
        raise AnalysisError('Unsupported or incomplete Phase 1 analysis report')
    root = Path(report['project_root']).resolve()
    relative = Path(report['target'])
    target = (root / relative).resolve()
    if not root.is_dir() or not target.is_file() or not target.is_relative_to(root):
        raise AnalysisError('The report target/repository is missing or invalid')
    output = (output_path or report_path.parent.parent).resolve()
    _outside(root, output)
    if _sha(target) != report.get('target_sha256'):
        raise AnalysisError('The target source changed since analysis. Re-run pseudotest analyze')
    for name, expected_sha in report.get('test_files_sha256', {}).items():
        test_path = (root / name).resolve()
        if not test_path.is_relative_to(root) or not test_path.is_file() or _sha(test_path) != expected_sha:
            raise AnalysisError('A test file changed since analysis. Re-run pseudotest analyze')
    candidate = [f for f in report['functions'] if f.get('status') == 'PSEUDO_TESTED_CANDIDATE']
    discovered = {f.key: f for f in discover(target, relative.as_posix())}
    for function in candidate:
        if function.get('id') not in discovered or function.get('return_type') not in DEFAULTS:
            raise AnalysisError('Invalid candidate function in report. Re-run analyze')
        mutants = function.get('mutants', [])
        values = DEFAULTS[function['return_type']]
        if (len(mutants) != 2 or any(m.get('status') != 'SURVIVED' or
            m.get('return_value') != repr(v) for m, v in zip(mutants, values))):
            raise AnalysisError('Invalid candidate mutations in report. Re-run analyze')
        if not function.get('selected_tests') or function.get('baseline_calls', 0) <= 0:
            raise AnalysisError('Candidate has no baseline evidence. Re-run analyze')
    args = shlex.split(report['test_command'])
    limit = float(timeout if timeout is not None else report.get('timeout_seconds', 60))
    if not 0 < limit < float('inf'):
        raise AnalysisError('--timeout must be positive and finite')
    config = Config(root, target, output, args, limit, Path(__file__).resolve().parent.parent)
    return report, config, candidate, discovered


def _test_file_source(source: str) -> str:
    """Accept only test modules, not prose; the resulting code remains untrusted."""
    source = source.strip()
    fence = re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```', source, flags=re.S | re.I)
    if fence:
        source = fence.group(1).strip()
    if len(source) > 16000:
        raise ValueError('Generated test code is too long')
    tree = ast.parse(source)
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
               node.name.startswith('test_') for node in tree.body):
        raise ValueError('No top-level pytest test_ function was generated')
    if any(isinstance(node, ast.AsyncFunctionDef) and node.name.startswith('test_')
           for node in tree.body):
        raise ValueError('Async pytest tests are outside Phase 2 initial support')
    return source + '\n'


def _prompt_for(config: Config, fn: dict, previous: list[str], feedback: str) -> str:
    source = config.target.read_text(encoding='utf-8')
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and
                 n.name == fn['name'] and n.lineno == fn['line']), None)
    if node is None:
        raise AnalysisError('Function definition changed; rerun analyze')
    function_source = ast.get_source_segment(source, node) or ''
    snippets = []
    for test_id in fn['selected_tests'][:12]:
        file_path = (config.root / test_id.split('::', 1)[0]).resolve()
        if not file_path.is_relative_to(config.root) or not file_path.is_file():
            continue
        test_source = file_path.read_text(encoding='utf-8')
        # Only include imports and the selected test's AST node, not the entire repo.
        try:
            test_tree = ast.parse(test_source)
        except SyntaxError:
            continue
        test_name = test_id.split('::')[-1].split('[', 1)[0]
        chosen = [ast.get_source_segment(test_source, n) or '' for n in test_tree.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == test_name]
        imports = [ast.get_source_segment(test_source, n) or '' for n in test_tree.body
                   if isinstance(n, (ast.Import, ast.ImportFrom))]
        snippets.append(f'Test node {test_id}:\n' + '\n'.join(imports + chosen)[:5000])
    values = DEFAULTS[fn['return_type']]
    return (f'Project module: {fn["path"]}\nTarget function: {fn["name"]}\n'
            f'Original function:\n```python\n{function_source}\n```\n'
            f'The two surviving mutants replace the function body with '\
            f'`return {values[0]!r}` and `return {values[1]!r}`.\n'
            'Current related tests (may omit helper fixtures):\n' + '\n\n'.join(snippets)[:12000] +
            '\nGenerate a self-contained pytest module with imports that work from '
            'the project root. Use correct existing project import conventions. '
            'Prefer concrete expected outputs based on the original function.\n'
            + ('Previously accepted partial tests:\n```python\n' + '\n'.join(previous) + '\n```\n' if previous else '')
            + ('Previous validation feedback:\n' + feedback[:1400] if feedback else ''))


def _validate(config: Config, source: str, test_name: str, fn: dict,
              original_source: str, workspace: Path) -> dict:
    """Run generated test + previous selected tests in fresh isolated copies."""
    relative = config.target.relative_to(config.root)
    pristine = workspace / 'pristine'
    copy_project(config.root, pristine)
    generated_rel = f'tests/{test_name}'
    if (pristine / generated_rel).exists():
        raise AnalysisError(f'Generated test path already exists in repo: {generated_rel}')
    function = next((f for f in discover(config.target, relative.as_posix())
                     if f.key == fn['id']), None)
    if function is None:
        raise AnalysisError('Function missing during validation')

    results = {}
    for variant, value in [('original', None), ('mutant1', DEFAULTS[fn['return_type']][0]),
                           ('mutant2', DEFAULTS[fn['return_type']][1])]:
        project_copy = workspace / variant
        copy_project(pristine, project_copy)
        new_test = project_copy / generated_rel
        new_test.parent.mkdir(parents=True, exist_ok=True)
        new_test.write_text(source, encoding='utf-8')
        if variant != 'original':
            mutated, _ = mutant_source(original_source, function, value)
            (project_copy / relative).write_text(mutated, encoding='utf-8')
        # Run ONLY generated tests here: any newly observed kill is attributable
        # to this generated set rather than to the original related tests.
        generated_run = run_pytest(config, project_copy, workspace / (variant + '-probe.json'),
                                   selected=[generated_rel])
        status = generated_run.get('status', 'ERROR')
        reason = generated_run.get('error', '')
        calls = 0
        outcomes = generated_run.get('probe', {}).get('items', {})
        generated_ids = generated_run.get('probe', {}).get('collected', [])
        if generated_run.get('status') == 'COMPLETE':
            if not generated_ids:
                status, reason = 'ERROR', 'No generated tests collected'
            elif generated_run.get('probe', {}).get('collection_error'):
                status, reason = 'ERROR', 'Generated test collection failed'
            else:
                states = [item_outcome(outcomes.get(n)) for n in generated_ids]
                calls = sum(outcomes.get(n, {}).get('calls', {}).get(fn['name'], 0)
                            for n in generated_ids)
                if 'SKIPPED' in states:
                    status, reason = 'SKIPPED', 'Generated test skipped'
                elif 'ERROR' in states:
                    status, reason = 'ERROR', 'Generated test had setup/teardown error'
                elif calls == 0:
                    status, reason = 'NOT_EXECUTED', 'Generated test did not execute the mutant'
                elif 'FAIL' in states:
                    # Only count a failed test that itself exercised the target;
                    # a failing unrelated generated test cannot kill a mutant.
                    failed_ids = [n for n in generated_ids if item_outcome(outcomes.get(n)) == 'FAIL']
                    if any(not outcomes.get(n, {}).get('calls', {}).get(fn['name'], 0)
                           for n in failed_ids):
                        status, reason = 'ERROR', 'A generated test failed without executing target'
                    elif variant == 'original':
                        status, reason = 'ERROR', 'Generated test failed on original function'
                    else:
                        status, reason = 'KILLED', 'Generated test detected the mutant'
                elif all(state == 'PASS' for state in states) and generated_run.get('returncode') == 0:
                    status, reason = 'PASS' if variant == 'original' else 'SURVIVED', 'Generated tests passed'
                else:
                    status, reason = 'ERROR', 'Generated test run was not conclusive'
        results[variant] = {'status': status, 'reason': reason, 'calls': calls,
                            'seconds': round(generated_run.get('seconds', 0), 3),
                            'stdout_tail': generated_run.get('stdout_tail', '')[-600:]}
        if variant == 'original' and status != 'PASS':
            break
    return results


def improve(report_path: Path, *, output: Path | None = None,
            timeout: float | None = None, api_timeout: float = 90,
            model: str = DEFAULT_MODEL, max_attempts: int = 3,
            generator: Callable[..., str] = create_test) -> dict:
    report, config, candidates, _ = _load_report(report_path.resolve(), output, timeout)
    if max_attempts < 1 or max_attempts > 10:
        raise AnalysisError('--max-attempts must be between 1 and 10')
    if not 0 < api_timeout < float('inf'):
        raise AnalysisError('--api-timeout must be positive and finite')
    # Check credentials before doing filesystem work; injected generators in tests are exempt.
    if generator is create_test and candidates:
        import os
        if not (os.getenv('NVIDIA_API_KEY') or os.getenv('NVIDIA_NIM_API_KEY')):
            raise AnalysisError('Set NVIDIA_API_KEY (or NVIDIA_NIM_API_KEY) before improve')
    config.output.mkdir(parents=True, exist_ok=True)
    generated_dir = config.output / 'generated-tests'
    results_dir = config.output / 'reports'
    for folder in (generated_dir, results_dir):
        if folder.is_symlink():
            raise AnalysisError('Output directory may not be a symbolic link')
        folder.mkdir(parents=True, exist_ok=True)
    original_source = config.target.read_text(encoding='utf-8')
    outcomes = []
    for fn in candidates:
        slug = re.sub(r'[^a-zA-Z0-9_]+', '_', fn['name'])[:40]
        name = f'test_pseudotest_{slug}_{fn["ordinal"]}.py'
        saved_source = []
        attempts = []
        feedback = ''
        success = False
        for attempt in range(1, max_attempts + 1):
            prompt = _prompt_for(config, fn, saved_source, feedback)
            try:
                raw = generator(prompt, model=model, timeout=api_timeout)
                proposed = _test_file_source(raw)
            except (ValueError, SyntaxError) as exc:
                feedback = f'Generated Python test was invalid: {exc}'
                attempts.append({'attempt': attempt, 'status': 'INVALID_CODE', 'reason': feedback})
                continue
            except AnalysisError as exc:
                attempts.append({'attempt': attempt, 'status': 'API_ERROR', 'reason': str(exc)})
                break
            # Compose tests across retries, allowing a pair of separately generated
            # tests to kill different mutants. Imports and pytest function names
            # must be valid in the combined module.
            combined = '\n\n'.join([*saved_source, proposed])
            try:
                merged_tree = ast.parse(combined)
                test_names = [node.name for node in merged_tree.body
                              if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
                if len(test_names) != len(set(test_names)):
                    raise ValueError('Duplicate pytest test function names; choose new names')
            except (SyntaxError, ValueError) as exc:
                feedback = f'Combined test code invalid: {exc}'
                attempts.append({'attempt': attempt, 'status': 'INVALID_CODE', 'reason': feedback})
                continue
            with tempfile.TemporaryDirectory(prefix='.pseudotest-improve-', dir=config.output) as temp:
                validation = _validate(config, combined, name, fn, original_source, Path(temp))
            states = {k: v['status'] for k, v in validation.items()}
            attempts.append({'attempt': attempt, 'status': 'VALIDATED', 'results': validation})
            if states.get('original') == 'PASS' and states.get('mutant1') == 'KILLED' and states.get('mutant2') == 'KILLED':
                dest = generated_dir / name
                if dest.exists() or dest.is_symlink():
                    raise AnalysisError(f'Generated file already exists: {dest}. Choose another --output')
                dest.write_text(combined, encoding='utf-8')
                success = True
                saved_source = [combined]
                break
            # Only preserve a test if it passed original and conclusively killed
            # at least one mutant. Otherwise replace it in the next attempt.
            if states.get('original') == 'PASS' and 'KILLED' in {states.get('mutant1'), states.get('mutant2')}:
                saved_source.append(proposed)
            else:
                saved_source = []
            feedback = ('Test run results: ' + json.dumps(validation, ensure_ascii=False)
                        + '\nWrite a DIFFERENT concrete behavioral assertion. '
                        'The new test must pass on original and kill remaining mutant(s).')
            if any(v in {'TIMEOUT', 'ERROR', 'SKIPPED', 'NOT_EXECUTED'}
                   for v in states.values()):
                # Environment or execution errors are not a valid AI improvement.
                # A wrong import can be corrected on retry; timeouts may recur.
                if 'TIMEOUT' in states.values():
                    break
        outcomes.append({'function': fn['id'], 'name': fn['name'],
                         'status': 'IMPROVED' if success else 'NOT_IMPROVED',
                         'generated_test': str(generated_dir / name) if success else None,
                         'attempts': attempts, 'mutation_score_before': 0,
                         'mutation_score_after': 100 if success else None})
    improvement = {'schema_version': 1, 'phase': 'improve',
                   'generated_at': datetime.now(timezone.utc).isoformat(),
                   'analysis_report': str(report_path.resolve()), 'model': model,
                   'functions': outcomes}
    destination = results_dir / 'improvement.json'
    if destination.is_symlink():
        raise AnalysisError('Improvement report path may not be a symbolic link')
    temporary = results_dir / 'improvement.json.tmp'
    temporary.write_text(json.dumps(improvement, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination)
    improvement['report_path'] = str(destination)
    return improvement
