"""Build notifications — Slack, webhooks, and other integrations.

Sends build events (failures, healed builds, recurring issues, deployments)
to external channels so teams don't have to watch GitHub Actions.

Supports:
  - Slack (via incoming webhook URL)
  - Generic webhook (POST JSON to any URL)

Configuration via environment variables:
  - SLACK_WEBHOOK_URL: Slack incoming webhook URL
  - NOTIFY_WEBHOOK_URL: Generic webhook URL (receives JSON POST)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

import requests

logger = logging.getLogger(__name__)


@dataclass
class BuildEvent:
    """A build event to send as a notification."""

    event_type: str  # build_success, build_failure, build_healed, recurring_failure, deployment
    repo: str = ""
    branch: str = ""
    commit_sha: str = ""
    version: str = ""
    duration_seconds: float = 0.0
    failure_class: str = ""
    healing_strategy: str = ""
    message: str = ""
    run_url: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _get_run_url() -> str:
    """Build the GitHub Actions run URL from environment."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"https://github.com/{repo}/actions/runs/{run_id}"
    return ""


def send_slack(event: BuildEvent, webhook_url: str | None = None) -> bool:
    """Send a build event to Slack via incoming webhook.

    Returns True if sent successfully.
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False

    color_map = {
        "build_success": "#36a64f",  # green
        "build_healed": "#daa520",  # goldenrod
        "build_failure": "#d93f0b",  # red
        "recurring_failure": "#ff0000",  # bright red
        "deployment": "#2196f3",  # blue
    }

    emoji_map = {
        "build_success": ":white_check_mark:",
        "build_healed": ":adhesive_bandage:",
        "build_failure": ":x:",
        "recurring_failure": ":rotating_light:",
        "deployment": ":rocket:",
    }

    color = color_map.get(event.event_type, "#808080")
    emoji = emoji_map.get(event.event_type, ":gear:")

    fields = []
    if event.repo:
        fields.append({"title": "Repository", "value": f"`{event.repo}`", "short": True})
    if event.branch:
        fields.append({"title": "Branch", "value": f"`{event.branch}`", "short": True})
    if event.version:
        fields.append({"title": "Version", "value": f"`{event.version}`", "short": True})
    if event.duration_seconds > 0:
        fields.append({"title": "Duration", "value": f"{event.duration_seconds:.0f}s", "short": True})
    if event.failure_class:
        fields.append({"title": "Failure Class", "value": f"`{event.failure_class}`", "short": True})
    if event.healing_strategy:
        fields.append({"title": "Strategy", "value": f"`{event.healing_strategy}`", "short": True})

    payload = {
        "attachments": [
            {
                "color": color,
                "fallback": f"{emoji} {event.event_type}: {event.repo} — {event.message}",
                "title": f"{emoji} {event.event_type.replace('_', ' ').title()}",
                "text": event.message,
                "fields": fields,
                "footer": "SCP CI Agent",
                "ts": None,
            }
        ]
    }

    if event.run_url:
        payload["attachments"][0]["title_link"] = event.run_url

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning("Slack webhook returned %d: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("Failed to send Slack notification: %s", e)
        return False


def send_webhook(event: BuildEvent, webhook_url: str | None = None) -> bool:
    """Send a build event to a generic webhook (POST JSON).

    Returns True if sent successfully.
    """
    url = webhook_url or os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url:
        return False

    try:
        resp = requests.post(url, json=event.to_dict(), timeout=10)
        if resp.status_code < 300:
            return True
        logger.warning("Webhook returned %d: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("Failed to send webhook notification: %s", e)
        return False


def notify(event: BuildEvent) -> dict[str, bool]:
    """Send a build event to all configured channels.

    Returns dict of {channel: success_bool}.
    """
    results = {}

    if os.environ.get("SLACK_WEBHOOK_URL"):
        results["slack"] = send_slack(event)

    if os.environ.get("NOTIFY_WEBHOOK_URL"):
        results["webhook"] = send_webhook(event)

    return results


def notify_build_result(
    status: str,
    build_type: str,
    failure_class: str = "",
    healing_strategy: str = "",
    duration: float = 0.0,
    version: str = "",
) -> dict[str, bool]:
    """Convenience function to notify about a build result.

    Only sends notifications for failures, healed builds, and deployments.
    Successful builds are silent by default (too noisy).
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "unknown")
    branch = os.environ.get("GITHUB_REF_NAME", "unknown")
    sha = os.environ.get("GITHUB_SHA", "unknown")[:7]
    run_url = _get_run_url()

    # Skip notifications for simple successes (too noisy)
    if status == "success" and not version:
        return {}

    event_type_map = {
        "success": "deployment" if version else "build_success",
        "failure": "build_failure",
        "healed": "build_healed",
    }

    message_map = {
        "success": f"Published `{version}` from `{branch}` ({sha})",
        "failure": f"Build failed on `{branch}` ({sha}) — `{failure_class}`",
        "healed": f"Build self-healed on `{branch}` ({sha}) — `{failure_class}` fixed by `{healing_strategy}`",
    }

    event = BuildEvent(
        event_type=event_type_map.get(status, status),
        repo=repo,
        branch=branch,
        commit_sha=sha,
        version=version,
        duration_seconds=duration,
        failure_class=failure_class,
        healing_strategy=healing_strategy,
        message=message_map.get(status, f"Build {status}"),
        run_url=run_url,
    )

    return notify(event)
