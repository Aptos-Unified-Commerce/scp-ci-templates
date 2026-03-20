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
    _write_github_output("repo-role", plan.repo_role)
    _write_github_output("project-type", plan.project_type)
    _write_github_output("deploy-target", plan.deploy_target)
    _write_github_output("has-dockerfile", str(plan.has_dockerfile).lower())
    _write_github_output("suggested-workflow", plan.suggested_workflow)
    _write_github_output("confidence", str(plan.confidence))

    if plan.security_warnings:
        summary = "### CI Agent Detection\n\n"
        summary += f"**Role:** {plan.repo_role} | "
        summary += f"**Project type:** {plan.project_type} | "
        summary += f"**Deploy target:** {plan.deploy_target} | "
        summary += f"**Confidence:** {plan.confidence:.0%}\n\n"
        summary += "#### Security Warnings\n"
        for warn in plan.security_warnings:
            summary += f"- {warn}\n"
        _write_step_summary(summary)


def cmd_heal(args: argparse.Namespace) -> None:
    from ci_agent.analyze.history import BuildHistory
    from ci_agent.heal.healer import Healer

    # Load build history for smart strategy ranking (closed-loop healing)
    records = None
    if args.history_file and os.path.exists(args.history_file):
        history = BuildHistory(history_file=args.history_file)
        records = history.records

    healer = Healer(records=records)

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


def cmd_version(args: argparse.Namespace) -> None:
    """Compute next semantic version from conventional commits."""
    from ci_agent.version.versioner import apply_version, compute_next_version, generate_changelog

    info = compute_next_version(args.repo_path)
    result = info.to_dict()

    print(json.dumps(result, indent=2))

    _write_github_output("current-version", info.current)
    _write_github_output("new-version", info.new)
    _write_github_output("bump-type", info.bump_type)

    if args.apply and info.bump_type != "none":
        modified = apply_version(args.repo_path, info.new)
        result["files_modified"] = modified
        _write_github_output("files-modified", ",".join(modified))

    changelog = generate_changelog(info)
    _write_github_output("changelog", changelog)

    summary = f"### Version: {info.current} → {info.new} ({info.bump_type})\n\n"
    summary += f"**Commits analyzed:** {info.commits_analyzed}\n\n"
    summary += changelog
    _write_step_summary(summary)


def cmd_security(args: argparse.Namespace) -> None:
    """Run security scans on the repository."""
    from ci_agent.security.scanner import SecurityScanner

    scanner = SecurityScanner(repo_path=args.repo_path, image=args.image)
    report = scanner.scan_all()

    print(report.to_json())

    _write_github_output("security-report", report.to_json())
    _write_github_output("total-findings", str(report.total))
    _write_github_output("has-critical", str(report.has_critical).lower())
    _write_github_output("has-high", str(report.has_high).lower())
    _write_step_summary(report.to_markdown())

    # Exit non-zero if critical or high findings and --fail-on-high is set
    if args.fail_on_high and (report.has_critical or report.has_high):
        print(f"\n::error::Security scan found {report.summary.get('critical', 0)} critical "
              f"and {report.summary.get('high', 0)} high severity issues")
        sys.exit(1)


def cmd_auto_issue(args: argparse.Namespace) -> None:
    """Check build history for recurring failures and create GitHub issues."""
    from ci_agent.analyze.history import BuildHistory
    from ci_agent.heal.issue_creator import create_recurring_failure_issue, should_create_issue
    from ci_agent.heal.scorer import StrategyScorer

    history = BuildHistory(history_file=args.history_file)
    scorer = StrategyScorer(history.records)
    recurring = scorer.get_recurring_failures(min_occurrences=args.min_occurrences)

    issues_created = []
    issues_skipped = []

    for failure in recurring:
        if not should_create_issue(
            failure["failure_class"],
            failure["total_attempts"],
            failure["success_rate"],
            min_attempts=args.min_occurrences,
        ):
            issues_skipped.append(failure["failure_class"])
            continue

        # Get recent branches affected
        recent_branches = list(set(
            r.branch for r in history.records
            if r.failure_class == failure["failure_class"] and r.branch
        ))[:5]

        url = create_recurring_failure_issue(
            failure_class=failure["failure_class"],
            total_attempts=failure["total_attempts"],
            success_rate=failure["success_rate"],
            strategies_tried=failure["strategies_tried"],
            recent_branches=recent_branches,
        )

        if url:
            issues_created.append({"failure_class": failure["failure_class"], "url": url})
        else:
            issues_skipped.append(failure["failure_class"])

    result = {
        "recurring_failures": recurring,
        "issues_created": issues_created,
        "issues_skipped": issues_skipped,
    }

    print(json.dumps(result, indent=2))

    _write_github_output("issues-created", str(len(issues_created)))
    _write_github_output("recurring-failures", str(len(recurring)))

    if issues_created or recurring:
        summary = "### CI Agent — Recurring Failure Check\n\n"
        summary += f"**Recurring failures detected:** {len(recurring)}\n"
        summary += f"**Issues created:** {len(issues_created)}\n\n"

        if issues_created:
            summary += "#### New Issues\n"
            for issue in issues_created:
                summary += f"- `{issue['failure_class']}` → [{issue['url']}]({issue['url']})\n"
            summary += "\n"

        if recurring:
            summary += "#### Recurring Failures\n"
            summary += "| Failure Class | Attempts | Success Rate | Needs Fix |\n"
            summary += "|--------------|----------|-------------|----------|\n"
            for f in recurring:
                needs_fix = "Yes" if f["needs_permanent_fix"] else "No"
                summary += f"| `{f['failure_class']}` | {f['total_attempts']} | {f['success_rate']:.0%} | {needs_fix} |\n"

        _write_step_summary(summary)


def cmd_preflight(args: argparse.Namespace) -> None:
    """Run predictive pre-flight checks before the build."""
    from ci_agent.analyze.history import BuildHistory
    from ci_agent.predict.preflight import PreflightPredictor

    records = []
    if os.path.exists(args.history_file):
        history = BuildHistory(history_file=args.history_file)
        records = history.records

    predictor = PreflightPredictor(records, repo_path=args.repo_path)
    result = predictor.predict()

    print(json.dumps(result.to_dict(), indent=2))

    _write_github_output("risk-level", result.risk_level)
    _write_github_output("risk-score", str(result.risk_score))
    if result.predicted_failure:
        _write_github_output("predicted-failure", result.predicted_failure)

    _write_step_summary(result.to_markdown())

    if args.fail_on_high and result.risk_level == "high":
        print(f"\n::warning::Pre-flight check: HIGH risk ({result.risk_score:.0%})")


def cmd_review_pr(args: argparse.Namespace) -> None:
    """Review the current PR diff for issues."""
    from ci_agent.review.pr_reviewer import PRReviewer, review_with_llm

    reviewer = PRReviewer(repo_path=args.repo_path, base_ref=args.base_ref)
    result = reviewer.review()

    print(json.dumps(result.to_dict(), indent=2))

    _write_github_output("review-approved", str(result.approved).lower())
    _write_github_output("review-errors", str(sum(1 for f in result.findings if f.severity == "error")))
    _write_github_output("review-warnings", str(sum(1 for f in result.findings if f.severity == "warning")))

    summary = result.to_markdown()

    # Optional LLM deep review
    if args.llm_review:
        diff = reviewer._get_diff()
        if diff:
            llm_review = review_with_llm(diff, result)
            if llm_review:
                summary += "\n\n### AI Deep Review\n\n" + llm_review

    _write_step_summary(summary)

    if args.fail_on_error and not result.approved:
        sys.exit(1)


def cmd_track_artifacts(args: argparse.Namespace) -> None:
    """Track AI artifacts (prompts, model configs) alongside code version."""
    from ci_agent.version.artifact_tracker import generate_manifest, has_artifacts_changed, load_manifest, save_manifest

    manifest = generate_manifest(
        repo_path=args.repo_path,
        code_version=args.version,
        commit_sha=os.environ.get("GITHUB_SHA", ""),
    )

    print(manifest.to_json())

    _write_github_output("artifact-count", str(len(manifest.artifacts)))
    _write_github_output("manifest-hash", manifest.manifest_hash)

    # Check if artifacts changed since last manifest
    if args.compare:
        old = load_manifest(args.compare)
        if old:
            changed = has_artifacts_changed(old, manifest)
            _write_github_output("artifacts-changed", str(changed).lower())
            if changed:
                _write_step_summary(
                    "### AI Artifacts Changed\n\n"
                    "Prompt or model config files changed since last build. "
                    "Consider bumping the version.\n\n" + manifest.to_markdown()
                )
            else:
                _write_step_summary("### AI Artifacts\n\nNo changes since last build.\n\n" + manifest.to_markdown())
        else:
            _write_step_summary(manifest.to_markdown())
    else:
        _write_step_summary(manifest.to_markdown())

    if args.output:
        save_manifest(manifest, args.output)
        print(f"Manifest saved to {args.output}")


def cmd_dep_graph(args: argparse.Namespace) -> None:
    """Register repo in the dependency graph or query it."""
    from pathlib import Path

    from ci_agent.deps.graph import DependencyGraph, register_repo

    graph = DependencyGraph.load(args.graph_file)

    if args.register:
        graph = register_repo(
            graph=graph,
            repo_name=args.repo_name,
            repo_role=args.repo_role,
            version=args.version,
            repo_path=Path(args.repo_path),
        )
        graph.save(args.graph_file)
        print(f"Registered {args.repo_name} ({args.repo_role}) in dependency graph")

    if args.query_cascade:
        targets = graph.get_cascade_targets(args.query_cascade)
        result = {"framework": args.query_cascade, "cascade_targets": targets}
        print(json.dumps(result, indent=2))
        _write_github_output("cascade-targets", ",".join(targets))
        if targets:
            _write_step_summary(
                f"### Cascade Build Targets\n\n"
                f"Framework `{args.query_cascade}` changed. These repos need rebuilding:\n"
                + "\n".join(f"- `{t}`" for t in targets)
            )

    if args.show:
        print(graph.to_json())
        _write_step_summary(graph.to_markdown())


def cmd_notify(args: argparse.Namespace) -> None:
    """Send build notification to Slack/webhooks."""
    from ci_agent.notify.sender import notify_build_result

    results = notify_build_result(
        status=args.status,
        build_type=args.build_type,
        failure_class=args.failure_class or "",
        healing_strategy=args.healing_strategy or "",
        duration=args.duration,
        version=args.version or "",
    )

    print(json.dumps(results, indent=2))

    if results:
        channels = ", ".join(f"{k}: {'sent' if v else 'failed'}" for k, v in results.items())
        _write_step_summary(f"### Notifications\n\n{channels}")


def cmd_docker_gen(args: argparse.Namespace) -> None:
    """Generate Dockerfile from golden template + repo config."""
    from ci_agent.docker.generator import generate_dockerfile

    from pathlib import Path

    template_path = Path(args.template)
    repo_path = Path(args.repo_path)
    output_path = Path(args.output)

    dockerfile = generate_dockerfile(template_path, repo_path, output_path)

    print(f"Generated Dockerfile → {output_path}")
    _write_github_output("dockerfile-path", str(output_path))

    summary = "### Dockerfile Generated\n\n"
    summary += f"**Template:** `{template_path}`\n"
    summary += f"**Output:** `{output_path}`\n\n"
    summary += "<details><summary>Generated Dockerfile</summary>\n\n"
    summary += f"```dockerfile\n{dockerfile}\n```\n\n</details>"
    _write_step_summary(summary)


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
    p_heal.add_argument("--history-file", default="build_history.json", help="Build history for smart strategy ranking")
    p_heal.set_defaults(func=cmd_heal)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze build history and generate report")
    p_analyze.add_argument("--history-file", default="build_history.json", help="Path to history file")
    p_analyze.set_defaults(func=cmd_analyze)

    # version
    p_version = subparsers.add_parser("version", help="Compute next semantic version from commits")
    p_version.add_argument("--repo-path", default=".", help="Path to the repository root")
    p_version.add_argument("--apply", action="store_true", help="Apply version to project files")
    p_version.set_defaults(func=cmd_version)

    # security
    p_security = subparsers.add_parser("security", help="Run security scans")
    p_security.add_argument("--repo-path", default=".", help="Path to the repository root")
    p_security.add_argument("--image", default=None, help="Docker image to scan (for agent repos)")
    p_security.add_argument("--fail-on-high", action="store_true", help="Exit non-zero on critical/high findings")
    p_security.set_defaults(func=cmd_security)

    # auto-issue
    p_issue = subparsers.add_parser("auto-issue", help="Create GitHub issues for recurring failures")
    p_issue.add_argument("--history-file", default="build_history.json", help="Build history file")
    p_issue.add_argument("--min-occurrences", type=int, default=3, help="Min healing attempts to trigger issue")
    p_issue.set_defaults(func=cmd_auto_issue)

    # preflight
    p_preflight = subparsers.add_parser("preflight", help="Predictive pre-flight check before build")
    p_preflight.add_argument("--repo-path", default=".", help="Path to the repo root")
    p_preflight.add_argument("--history-file", default="build_history.json", help="Build history file")
    p_preflight.add_argument("--fail-on-high", action="store_true", help="Warn if risk is high")
    p_preflight.set_defaults(func=cmd_preflight)

    # review-pr
    p_review = subparsers.add_parser("review-pr", help="Review PR diff for issues")
    p_review.add_argument("--repo-path", default=".", help="Path to the repo root")
    p_review.add_argument("--base-ref", default="main", help="Base branch to diff against")
    p_review.add_argument("--llm-review", action="store_true", help="Include LLM deep review")
    p_review.add_argument("--fail-on-error", action="store_true", help="Exit non-zero if errors found")
    p_review.set_defaults(func=cmd_review_pr)

    # track-artifacts
    p_artifacts = subparsers.add_parser("track-artifacts", help="Track AI artifacts (prompts, model configs)")
    p_artifacts.add_argument("--repo-path", default=".", help="Path to the repo root")
    p_artifacts.add_argument("--version", default="0.0.0", help="Current code version")
    p_artifacts.add_argument("--output", default=None, help="Save manifest to this file")
    p_artifacts.add_argument("--compare", default=None, help="Compare against previous manifest file")
    p_artifacts.set_defaults(func=cmd_track_artifacts)

    # dep-graph
    p_deps = subparsers.add_parser("dep-graph", help="Manage the cross-repo dependency graph")
    p_deps.add_argument("--graph-file", default="dep_graph.json", help="Path to the dependency graph file")
    p_deps.add_argument("--repo-path", default=".", help="Path to the repo root")
    p_deps.add_argument("--register", action="store_true", help="Register this repo in the graph")
    p_deps.add_argument("--repo-name", default=os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "unknown", help="Repo name")
    p_deps.add_argument("--repo-role", default="framework", help="Repo role (framework/agent)")
    p_deps.add_argument("--version", default="0.0.0", help="Current repo version")
    p_deps.add_argument("--query-cascade", default=None, help="Query cascade targets for a framework name")
    p_deps.add_argument("--show", action="store_true", help="Show the full dependency graph")
    p_deps.set_defaults(func=cmd_dep_graph)

    # notify
    p_notify = subparsers.add_parser("notify", help="Send build notification to Slack/webhooks")
    p_notify.add_argument("--status", required=True, help="Build status (success/failure/healed)")
    p_notify.add_argument("--build-type", default="unknown", help="Build type (framework/agent)")
    p_notify.add_argument("--failure-class", default=None, help="Failure class (if failed)")
    p_notify.add_argument("--healing-strategy", default=None, help="Healing strategy (if healed)")
    p_notify.add_argument("--duration", type=float, default=0.0, help="Build duration in seconds")
    p_notify.add_argument("--version", default=None, help="Published version (triggers deployment notification)")
    p_notify.set_defaults(func=cmd_notify)

    # docker-gen
    p_docker = subparsers.add_parser("docker-gen", help="Generate Dockerfile from golden template")
    p_docker.add_argument("--template", required=True, help="Path to golden Dockerfile template")
    p_docker.add_argument("--repo-path", default=".", help="Path to the caller repo root")
    p_docker.add_argument("--output", default="Dockerfile", help="Output path for generated Dockerfile")
    p_docker.set_defaults(func=cmd_docker_gen)

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
