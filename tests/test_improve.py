"""Phase 2 tests use an offline fake generator; no NVIDIA credentials are needed."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pseudotest.cli import main
from pseudotest.improve import improve
from pseudotest.model import AnalysisError

SAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'sample_repo'


def _snapshot(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


def _report(monkeypatch, tmp_path):
    root = tmp_path / 'target_repo'
    shutil.copytree(SAMPLE, root)
    out = tmp_path / 'output'
    monkeypatch.chdir(root)
    assert main(['analyze', '--target', 'src/calculator.py', '--test-cmd',
                 'python -m pytest tests/ -q', '--output', str(out), '--timeout', '25']) == 0
    return root, out, out / 'results' / 'analysis.json'


def _fake(prompt, **kwargs):
    assert 'discount' in prompt
    assert 'return 0.0' in prompt
    assert 'return 1.0' in prompt
    return '''from src.calculator import discount

def test_discount_exact_behavior():
    assert discount(100) == 90.0
'''


def test_improve_end_to_end_without_modifying_repository(monkeypatch, tmp_path):
    root, out, report = _report(monkeypatch, tmp_path)
    before = _snapshot(root)
    result = improve(report, generator=_fake, max_attempts=1)
    assert _snapshot(root) == before
    assert len(result['functions']) == 1
    fn = result['functions'][0]
    assert fn['status'] == 'IMPROVED'
    assert fn['mutation_score_before'] == 0
    assert fn['mutation_score_after'] == 100
    assert Path(fn['generated_test']).is_file()
    assert Path(fn['generated_test']).is_relative_to(out)
    statuses = {k: v['status'] for k, v in fn['attempts'][0]['results'].items()}
    assert statuses == {'original': 'PASS', 'mutant1': 'KILLED', 'mutant2': 'KILLED'}
    assert not list(out.glob('.pseudotest-improve-*'))
    assert (out / 'reports' / 'improvement.json').is_file()


def test_rejects_stale_report(monkeypatch, tmp_path):
    root, out, report = _report(monkeypatch, tmp_path)
    path = root / 'src' / 'calculator.py'
    path.write_text(path.read_text() + '\n# changed\n')
    with pytest.raises(AnalysisError, match='changed'):
        improve(report, generator=_fake, max_attempts=1)
    assert not (out / 'generated-tests').exists()


def test_invalid_generated_code_is_not_saved(monkeypatch, tmp_path):
    _, out, report = _report(monkeypatch, tmp_path)
    result = improve(report, generator=lambda *a, **k: 'garbage(', max_attempts=1)
    fn = result['functions'][0]
    assert fn['status'] == 'NOT_IMPROVED'
    assert fn['generated_test'] is None
    assert fn['attempts'][0]['status'] == 'INVALID_CODE'
    assert not list((out / 'generated-tests').glob('*.py'))


def test_does_not_accept_test_that_passes_on_mutants(monkeypatch, tmp_path):
    _, out, report = _report(monkeypatch, tmp_path)
    def fake(*args, **kwargs):
        return '''from src.calculator import discount

def test_discount_weak():
    assert discount(100) >= 0
'''
    result = improve(report, generator=fake, max_attempts=1)
    assert result['functions'][0]['status'] == 'NOT_IMPROVED'
    assert not list((out / 'generated-tests').glob('*.py'))
