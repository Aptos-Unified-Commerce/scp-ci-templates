"""Tests for the notification module."""

from unittest.mock import patch, MagicMock

import pytest

from ci_agent.notify.sender import BuildEvent, notify, notify_build_result, send_slack, send_webhook


@pytest.fixture
def sample_event():
    return BuildEvent(
        event_type="build_failure",
        repo="Aptos-Unified-Commerce/scp-agent-orders",
        branch="main",
        commit_sha="abc1234",
        failure_class="dependency-conflict",
        message="Build failed on main",
        run_url="https://github.com/org/repo/actions/runs/123",
    )


def test_build_event_to_dict(sample_event):
    d = sample_event.to_dict()
    assert d["event_type"] == "build_failure"
    assert d["repo"] == "Aptos-Unified-Commerce/scp-agent-orders"


def test_send_slack_no_url():
    event = BuildEvent(event_type="build_failure", message="test")
    assert send_slack(event) is False


def test_send_webhook_no_url():
    event = BuildEvent(event_type="build_failure", message="test")
    assert send_webhook(event) is False


@patch("ci_agent.notify.sender.requests.post")
def test_send_slack_success(mock_post, sample_event):
    mock_post.return_value = MagicMock(status_code=200)
    result = send_slack(sample_event, webhook_url="https://hooks.slack.com/test")
    assert result is True
    mock_post.assert_called_once()

    # Verify payload structure
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert "attachments" in payload
    assert payload["attachments"][0]["color"] == "#d93f0b"  # red for failure


@patch("ci_agent.notify.sender.requests.post")
def test_send_webhook_success(mock_post, sample_event):
    mock_post.return_value = MagicMock(status_code=200)
    result = send_webhook(sample_event, webhook_url="https://example.com/webhook")
    assert result is True


@patch("ci_agent.notify.sender.requests.post")
def test_send_slack_failure(mock_post, sample_event):
    mock_post.return_value = MagicMock(status_code=500, text="error")
    result = send_slack(sample_event, webhook_url="https://hooks.slack.com/test")
    assert result is False


def test_notify_no_channels_configured():
    event = BuildEvent(event_type="build_failure", message="test")
    with patch.dict("os.environ", {}, clear=True):
        results = notify(event)
    assert results == {}


@patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
@patch("ci_agent.notify.sender.requests.post")
def test_notify_sends_to_slack(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    event = BuildEvent(event_type="build_failure", message="test")
    results = notify(event)
    assert results["slack"] is True


def test_notify_build_result_skips_simple_success():
    """Simple successes don't trigger notifications (too noisy)."""
    with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}):
        results = notify_build_result(status="success", build_type="framework")
    assert results == {}


@patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test", "GITHUB_REPOSITORY": "org/repo"})
@patch("ci_agent.notify.sender.requests.post")
def test_notify_build_result_sends_on_failure(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    results = notify_build_result(
        status="failure",
        build_type="agent",
        failure_class="dependency-conflict",
    )
    assert results["slack"] is True
