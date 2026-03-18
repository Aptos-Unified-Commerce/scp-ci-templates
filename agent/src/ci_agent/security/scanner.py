"""Security scanning orchestrator.

Runs available security tools and aggregates results into a unified report.

Tools used (free, no license needed):
  - pip-audit:  Python dependency vulnerability scanning (OSV database)
  - bandit:     Python SAST (static analysis for security issues)
  - trivy:      Container image + filesystem vulnerability scanning
  - hadolint:   Dockerfile best-practice linting
  - gitleaks:   Secret detection in code and git history

Future: Snyk integration will replace pip-audit and trivy.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SecurityFinding:
    tool: str
    severity: str  # critical, high, medium, low, info
    category: str  # vulnerability, secret, sast, dockerfile, license
    title: str
    description: str
    file: str = ""
    line: int = 0
    fix: str = ""


@dataclass
class SecurityReport:
    findings: list[SecurityFinding] = field(default_factory=list)
    tools_run: list[str] = field(default_factory=list)
    tools_skipped: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)  # severity → count

    def add(self, finding: SecurityFinding) -> None:
        self.findings.append(finding)
        self.summary[finding.severity] = self.summary.get(finding.severity, 0) + 1

    @property
    def has_critical(self) -> bool:
        return self.summary.get("critical", 0) > 0

    @property
    def has_high(self) -> bool:
        return self.summary.get("high", 0) > 0

    @property
    def total(self) -> int:
        return len(self.findings)

    def to_json(self) -> str:
        return json.dumps({
            "findings": [asdict(f) for f in self.findings],
            "tools_run": self.tools_run,
            "tools_skipped": self.tools_skipped,
            "summary": self.summary,
            "total": self.total,
        }, indent=2)

    def to_markdown(self) -> str:
        lines = ["## Security Scan Report\n"]

        # Summary table
        lines.append("### Summary\n")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        for sev in ["critical", "high", "medium", "low", "info"]:
            count = self.summary.get(sev, 0)
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}.get(sev, "")
            if count > 0:
                lines.append(f"| {emoji} {sev.upper()} | {count} |")
        lines.append(f"| **Total** | **{self.total}** |\n")

        lines.append(f"**Tools run:** {', '.join(self.tools_run)}")
        if self.tools_skipped:
            lines.append(f"**Tools skipped:** {', '.join(self.tools_skipped)}")
        lines.append("")

        # Findings by category
        if self.findings:
            lines.append("### Findings\n")
            lines.append("<details><summary>Click to expand</summary>\n")
            for f in sorted(self.findings, key=lambda x: ["critical", "high", "medium", "low", "info"].index(x.severity)):
                lines.append(f"- **[{f.severity.upper()}]** `{f.tool}` — {f.title}")
                if f.file:
                    loc = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
                    lines.append(f"  - Location: {loc}")
                if f.description:
                    lines.append(f"  - {f.description}")
                if f.fix:
                    lines.append(f"  - Fix: {f.fix}")
            lines.append("\n</details>")

        return "\n".join(lines)


def _tool_available(name: str) -> bool:
    """Check if a CLI tool is available on PATH."""
    try:
        subprocess.run([name, "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class SecurityScanner:
    """Orchestrates multiple security scanning tools."""

    def __init__(self, repo_path: str = ".", image: str | None = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.image = image  # Docker image URI for container scanning
        self.report = SecurityReport()

    def scan_all(self) -> SecurityReport:
        """Run all available security scans."""
        self._run_pip_audit()
        self._run_bandit()
        self._run_gitleaks()
        self._run_hadolint()
        self._run_trivy_fs()
        if self.image:
            self._run_trivy_image()
        return self.report

    def _run_pip_audit(self) -> None:
        """Scan Python dependencies for known vulnerabilities."""
        if not (self.repo_path / "pyproject.toml").exists() and not (self.repo_path / "requirements.txt").exists():
            return

        if not _tool_available("pip-audit"):
            self.report.tools_skipped.append("pip-audit")
            return

        self.report.tools_run.append("pip-audit")
        try:
            result = subprocess.run(
                ["pip-audit", "--format=json", "--desc", "--output=-"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=120,
            )
            if result.stdout.strip():
                data = json.loads(result.stdout)
                for dep in data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        severity = self._map_pip_audit_severity(vuln.get("id", ""))
                        self.report.add(SecurityFinding(
                            tool="pip-audit",
                            severity=severity,
                            category="vulnerability",
                            title=f"{dep['name']} {dep['version']} — {vuln.get('id', 'unknown')}",
                            description=vuln.get("description", "")[:200],
                            fix=vuln.get("fix_versions", [""])[0] if vuln.get("fix_versions") else "",
                        ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _run_bandit(self) -> None:
        """Run Python SAST with bandit."""
        src_dirs = [d for d in ["src", "app", "."] if (self.repo_path / d).is_dir()]
        if not src_dirs:
            return

        if not _tool_available("bandit"):
            self.report.tools_skipped.append("bandit")
            return

        self.report.tools_run.append("bandit")
        try:
            result = subprocess.run(
                ["bandit", "-r", src_dirs[0], "-f", "json", "-q",
                 "--exclude", ".venv,venv,node_modules,dist,build,__pycache__,.ci-templates"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=120,
            )
            if result.stdout.strip():
                data = json.loads(result.stdout)
                for issue in data.get("results", []):
                    self.report.add(SecurityFinding(
                        tool="bandit",
                        severity=issue.get("issue_severity", "medium").lower(),
                        category="sast",
                        title=f"{issue.get('test_id', '')} — {issue.get('issue_text', '')}",
                        description=issue.get("more_info", ""),
                        file=issue.get("filename", ""),
                        line=issue.get("line_number", 0),
                    ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _run_gitleaks(self) -> None:
        """Scan for secrets in code and git history."""
        if not _tool_available("gitleaks"):
            self.report.tools_skipped.append("gitleaks")
            return

        self.report.tools_run.append("gitleaks")
        try:
            result = subprocess.run(
                ["gitleaks", "detect", "--source", str(self.repo_path),
                 "--report-format", "json", "--report-path", "/dev/stdout",
                 "--no-banner"],
                capture_output=True, text=True, timeout=120,
            )
            if result.stdout.strip():
                findings = json.loads(result.stdout)
                if isinstance(findings, list):
                    for leak in findings:
                        self.report.add(SecurityFinding(
                            tool="gitleaks",
                            severity="high",
                            category="secret",
                            title=f"Secret detected: {leak.get('RuleID', 'unknown')}",
                            description=leak.get("Description", ""),
                            file=leak.get("File", ""),
                            line=leak.get("StartLine", 0),
                        ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _run_hadolint(self) -> None:
        """Lint Dockerfile for best practices."""
        dockerfile = self.repo_path / "Dockerfile"
        if not dockerfile.exists():
            return

        if not _tool_available("hadolint"):
            self.report.tools_skipped.append("hadolint")
            return

        self.report.tools_run.append("hadolint")
        try:
            result = subprocess.run(
                ["hadolint", str(dockerfile), "-f", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.stdout.strip():
                findings = json.loads(result.stdout)
                for issue in findings:
                    severity = {"error": "high", "warning": "medium", "info": "low", "style": "info"}.get(
                        issue.get("level", "info"), "info"
                    )
                    self.report.add(SecurityFinding(
                        tool="hadolint",
                        severity=severity,
                        category="dockerfile",
                        title=f"{issue.get('code', '')} — {issue.get('message', '')}",
                        description="",
                        file="Dockerfile",
                        line=issue.get("line", 0),
                    ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _run_trivy_fs(self) -> None:
        """Scan filesystem for vulnerabilities (deps, IaC, secrets)."""
        if not _tool_available("trivy"):
            self.report.tools_skipped.append("trivy")
            return

        self.report.tools_run.append("trivy-fs")
        try:
            result = subprocess.run(
                ["trivy", "fs", "--format", "json", "--scanners", "vuln,secret,misconfig",
                 "--severity", "CRITICAL,HIGH,MEDIUM", str(self.repo_path)],
                capture_output=True, text=True, timeout=180,
            )
            if result.stdout.strip():
                self._parse_trivy_output(result.stdout, "trivy-fs")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _run_trivy_image(self) -> None:
        """Scan a Docker image for vulnerabilities."""
        if not self.image or not _tool_available("trivy"):
            return

        self.report.tools_run.append("trivy-image")
        try:
            result = subprocess.run(
                ["trivy", "image", "--format", "json", "--severity", "CRITICAL,HIGH,MEDIUM",
                 self.image],
                capture_output=True, text=True, timeout=300,
            )
            if result.stdout.strip():
                self._parse_trivy_output(result.stdout, "trivy-image")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

    def _parse_trivy_output(self, output: str, tool_name: str) -> None:
        """Parse trivy JSON output into findings."""
        try:
            data = json.loads(output)
            results = data.get("Results", [])
            for result in results:
                for vuln in result.get("Vulnerabilities", []):
                    severity = vuln.get("Severity", "UNKNOWN").lower()
                    if severity == "unknown":
                        severity = "info"
                    self.report.add(SecurityFinding(
                        tool=tool_name,
                        severity=severity,
                        category="vulnerability",
                        title=f"{vuln.get('PkgName', '')} {vuln.get('InstalledVersion', '')} — {vuln.get('VulnerabilityID', '')}",
                        description=vuln.get("Title", "")[:200],
                        fix=vuln.get("FixedVersion", ""),
                    ))
                for secret in result.get("Secrets", []):
                    self.report.add(SecurityFinding(
                        tool=tool_name,
                        severity="high",
                        category="secret",
                        title=f"Secret: {secret.get('RuleID', '')}",
                        description=secret.get("Title", ""),
                        file=secret.get("Target", ""),
                        line=secret.get("StartLine", 0),
                    ))
        except (json.JSONDecodeError, KeyError):
            pass

    @staticmethod
    def _map_pip_audit_severity(vuln_id: str) -> str:
        """Map pip-audit vulnerability IDs to severity levels."""
        # pip-audit doesn't always include severity; default to high for CVEs
        if vuln_id.startswith("GHSA-"):
            return "high"
        if vuln_id.startswith("CVE-"):
            return "high"
        if vuln_id.startswith("PYSEC-"):
            return "medium"
        return "medium"
