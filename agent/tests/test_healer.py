"""Tests for the healing module."""

import pytest

from ci_agent.heal.healer import Healer


@pytest.fixture
def healer():
    return Healer()


def test_classify_dependency_conflict(healer):
    log = """
    Collecting fastapi>=0.100
    ERROR: ResolutionImpossible: Cannot install fastapi>=0.100 and starlette<0.20
    """
    action = healer.diagnose(log)

    assert action.failure_class == "dependency-conflict"
    assert action.strategy == "clear-lockfile-retry"
    assert action.should_retry is True


def test_classify_test_failure(healer):
    log = """
    FAILED tests/test_api.py::test_create_user - AssertionError: 200 != 404
    ========= 1 failed, 12 passed in 3.45s =========
    """
    action = healer.diagnose(log)

    assert action.failure_class == "test-failure"
    assert action.should_retry is True


def test_classify_timeout(healer):
    log = """
    requests.exceptions.ReadTimeoutError: HTTPSConnectionPool timed out
    """
    action = healer.diagnose(log)

    assert action.failure_class == "network-timeout"
    assert action.strategy == "retry-with-timeout"


def test_classify_rate_limit(healer):
    log = """
    HTTP Error 429: Too Many Requests
    """
    action = healer.diagnose(log)

    assert action.failure_class == "rate-limit"
    assert "sleep" in action.retry_commands[0]


def test_classify_oom(healer):
    log = """
    FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
    """
    action = healer.diagnose(log)

    assert action.failure_class == "oom"
    assert action.strategy == "reduce-parallelism"


def test_classify_docker_failure(healer):
    log = """
    ERROR [stage-2 3/5] RUN pip install -r requirements.txt
    executor failed running [/bin/sh -c pip install -r requirements.txt]
    """
    action = healer.diagnose(log)

    assert action.failure_class == "docker-build-failure"
    assert action.strategy == "docker-no-cache"


def test_classify_import_error(healer):
    log = """
    ModuleNotFoundError: No module named 'my_package'
    """
    action = healer.diagnose(log)

    assert action.failure_class == "import-error"
    assert action.strategy == "reinstall-deps"


def test_unknown_failure(healer):
    log = "Something completely unexpected happened"
    action = healer.diagnose(log)

    assert action.failure_class == "unknown"
    assert action.should_retry is False


def test_max_retries_exceeded(healer):
    log = """
    FAILED tests/test_api.py::test_create_user - AssertionError
    """
    # test-failure has max_retries=1
    action = healer.diagnose(log, attempt=2)

    assert action.failure_class == "test-failure"
    assert action.should_retry is False
