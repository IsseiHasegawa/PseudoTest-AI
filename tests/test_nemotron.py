"""Verify NVIDIA request format without making a network request."""
import json

import pytest

from pseudotest.model import AnalysisError
from pseudotest import nemotron


def test_requires_key(monkeypatch):
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.delenv('NVIDIA_NIM_API_KEY', raising=False)
    with pytest.raises(AnalysisError, match='NVIDIA_API_KEY'):
        nemotron.create_test('write a test')


def test_chat_completion_request(monkeypatch):
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-api-key-not-real')

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, *args):
            return json.dumps({'choices': [{'message': {'content': 'def test_example():\n    assert True'}}]}).encode()

    def fake_open(request, timeout):
        assert request.full_url == nemotron.API_URL
        assert request.get_header('Authorization') == 'Bearer test-api-key-not-real'
        assert timeout == 18
        data = json.loads(request.data)
        assert data['model'] == 'nvidia/nemotron-3-super-120b-a12b'
        assert data['messages'][-1]['content'] == 'write a test'
        return FakeResponse()

    monkeypatch.setattr(nemotron, 'urlopen', fake_open)
    code = nemotron.create_test('write a test', timeout=18)
    assert code.startswith('def test_example')
