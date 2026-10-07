"""Disposable browser case boundaries preserve auth limits inside each case."""
import time
import pytest
from fastapi.testclient import TestClient
from member_dashboard.auth import AuthError
from member_dashboard.synthetic import create_synthetic


def test_boundary_resets_anonymous_challenges_only_when_explicitly_requested(tmp_path):
    app = create_synthetic(tmp_path.resolve())
    now = time.time()
    original = app.state.anonymous_csrf
    for _ in range(50):
        original.issue(now, 'testclient')
    with pytest.raises(AuthError):
        original.issue(now, 'testclient')
    client = TestClient(app, base_url='https://localhost:3443')
    assert client.get('/__fixture/control').status_code == 405
    assert app.state.anonymous_csrf is original
    assert client.post('/__fixture/control', json={'action':'auth_test_boundary'}).status_code == 200
    assert app.state.anonymous_csrf is not original
    assert app.state.anonymous_csrf.issue(now, 'testclient')
