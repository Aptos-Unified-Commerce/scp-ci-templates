"""CLI entry point: ci-agent detect|heal|analyze."""

from __future__ import annotations

import argparse
import json
import os
import sys


def _write_github_output(key: str, value: str) -> None:
    """Write a key=value pair to GITHUB_OUTPUT if running in Actions."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            if "\n" in value:
                import uuid

                delimiter = uuid.uuid4().hex
                f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                f.write(f"{key}={value}\n")


def _write_step_summary(markdown: str) -> None:
    """Append markdown to GITHUB_STEP_SUMMARY."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write(markdown + "\n")


def cmd_detect(args: argparse.Namespace) -> None:
    from ci_agent.detect.detector import Detector

    detector = Detector(repo_path=args.repo_path)
    plan = detector.detect()

    print(plan.to_json())

    _write_github_output("build-plan", plan.to_json())
    _write_github_output("project-type", plan.project_type)
    _write_github_output("deploy-target", plan.deploy_target)
    _write_github_output("has-dockerfile", str(plan.has_dockerfile).lower())
    _write_github_output("suggested-workflow", plan.suggested_workflow)
    _write_github_output("confidence", str(plan.confidence))

    if plan.security_warnings:
        summary = "### CI Agent Detection\n\n"
        summary += f"**Project type:** {plan.project_type} | "
        summary += f"**Deploy target:** {plan.deploy_target} | "
        summary += f"**Confidence:** {plan.confidence:.0%}\n\n"
        summary += "#### Security Warnings\n"
        for warn in plan.security_warnings:
            summary += f"- {warn}\n"
        _write_step_summary(summary)


def cmd_heal(args: argparse.Namespace) -> None:
    from ci_agent.heal.healer import Healer

    healer = Healer()

    log_content = ""
    if args.log_file and os.path.exists(args.log_file):
        with open(args.log_file) as f:
            log_content = f.read()

    action = healer.diagnose(log_content, attempt=args.attempt)

    print(action.to_json())

    _write_github_output("healing-action", action.to_json())
    _write_github_output("failure-class", action.failure_class)
    _write_github_output("strategy", action.strategy)
    _write_github_output("should-retry", str(action.should_retry).lower())

    if action.retry_commands:
        _write_github_output("retry-commands", "\n".join(action.retry_commands))
    if action.retry_env:
        _write_github_output("retry-env", json.dumps(action.retry_env))

    summary = "### CI Agent Healing\n\n"
    summary += f"**Failure class:** `{action.failure_class}`\n"
    summary += f"**Strategy:** {action.strategy}\n"
    summary += f"**Attempt:** {args.attempt}\n"
    summary += f"**Will retry:** {action.should_retry}\n\n"
    summary += f"**Explanation:** {action.explanation}\n"
    _write_step_summary(summary)

    if action.needs_code_fix and not action.should_retry:
        sys.exit(1)


def cmd_analyze(args: argparse.Namespace) -> None:
    from ci_agent.analyze.analyzer import Analyzer

    analyzer = Analyzer(history_file=args.history_file)
    report = analyzer.analyze()

    print(report.to_json())

    _write_github_output("analysis-report", report.to_json())
    _write_step_summary(report.to_markdown())


def cmd_record(args: argparse.Namespace) -> None:
    """Record a build result to history."""
    from ci_agent.analyze.history import BuildHistory
    from ci_agent.models import BuildRecord

    history = BuildHistory(history_file=args.history_file)

    record = BuildRecord(
        run_id=int(os.environ.get("GITHUB_RUN_ID", 0)),
        branch=os.environ.get("GITHUB_REF_NAME", "unknown"),
        commit_sha=os.environ.get("GITHUB_SHA", "unknown"),
        build_type=args.build_type,
        duration_seconds=args.duration,
        status=args.status,
        failure_class=args.failure_class,
        healing_strategy=args.healing_strategy,
    )

    history.add(record)
    history.save()
    print(f"Recorded build {record.run_id} ({record.status})")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ci-agent",
        description="Autonomous CI/CD Agent — detect, heal, analyze",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect
    p_detect = subparsers.add_parser("detect", help="Detect project type and generate build plan")
    p_detect.add_argument("--repo-path", default=".", help="Path to the repository root")
    p_detect.set_defaults(func=cmd_detect)

    # heal
    p_heal = subparsers.add_parser("heal", help="Analyze failure and suggest healing strategy")
    p_heal.add_argument("--log-file", required=True, help="Path to the build log file")
    p_heal.add_argument("--attempt", type=int, default=1, help="Current retry attempt number")
    p_heal.set_defaults(func=cmd_heal)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze build history and generate report")
    p_analyze.add_argument("--history-file", default="build_history.json", help="Path to history file")
    p_analyze.set_defaults(func=cmd_analyze)

    # record
    p_record = subparsers.add_parser("record", help="Record a build result to history")
    p_record.add_argument("--history-file", default="build_history.json", help="Path to history file")
    p_record.add_argument("--build-type", required=True, help="Build type (python, docker, node, go)")
    p_record.add_argument("--status", required=True, help="Build status (success, failure, healed)")
    p_record.add_argument("--duration", type=float, default=0.0, help="Build duration in seconds")
    p_record.add_argument("--failure-class", default=None, help="Failure classification")
    p_record.add_argument("--healing-strategy", default=None, help="Healing strategy used")
    p_record.set_defaults(func=cmd_record)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
