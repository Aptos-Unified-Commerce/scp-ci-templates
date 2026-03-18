# SCP CI Templates

Autonomous CI/CD platform for SCP services with smart detection, self-healing, and build analytics.

## Architecture: Frameworks & Agents

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  FRAMEWORKS (libraries)              AGENTS (services)           │
│  ┌────────────────────┐              ┌────────────────────┐      │
│  │ scp-ai-platform    │              │ scp-agent-test-    │      │
│  │ (no Dockerfile)    │──publishes──▶│ runner             │      │
│  │                    │   to         │ (has Dockerfile)   │      │
│  └────────┬───────────┘  CodeArtifact└────────┬───────────┘      │
│           │                                   │                  │
│     uv build + test                   uv test + docker build     │
│           │                                   │                  │
│           ▼                                   ▼                  │
│   ┌───────────────┐                  ┌───────────────┐           │
│   │ CodeArtifact  │                  │     ECR       │           │
│   │ (Python pkgs) │                  │ (Docker imgs) │           │
│   └───────────────┘                  └───────────────┘           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

| Repo Type | What it is | Build | Publish to | Workflow |
|-----------|-----------|-------|------------|----------|
| **Framework** | Shared Python library (e.g., `scp-ai-platform`) | `uv build` → wheel + sdist | **CodeArtifact** | `ci-framework.yml` |
| **Agent** | Python service with Dockerfile (e.g., `scp-agent-test-runner`) | `uv test` → `docker build` | **ECR** | `ci-agent-service.yml` |

The CI agent **auto-detects** which type your repo is:
- **No Dockerfile** → Framework → CodeArtifact
- **Has Dockerfile** → Agent → ECR (pulls framework libs from CodeArtifact during build)

---

## Create a New Repo

Scaffold a new framework or agent repo with a single command:

```bash
# Clone this repo (one-time)
git clone git@github.com:Aptos-Unified-Commerce/scp-ci-templates.git

# Create a framework (library → CodeArtifact)
./scp-ci-templates/create-repo.sh framework scp-auth-lib "Shared authentication library"

# Create an agent (service → ECR)
./scp-ci-templates/create-repo.sh agent scp-agent-orders "Order processing agent service"
```

This generates a ready-to-go repo with:

| | Framework | Agent |
|--|-----------|-------|
| `pyproject.toml` | Library config, version `0.0.1` | Service config with FastAPI |
| `.github/workflows/ci.yml` | Calls shared template | Calls shared template (with ECR) |
| `.gitignore` | Python defaults | Python + Docker defaults |
| `src/{package}/` | `__init__.py` | `__init__.py` + `main.py` (FastAPI /health) |
| `tests/` | Placeholder import test | Health endpoint test |
| `Dockerfile` | -- | Python 3.11, non-root user, uvicorn |
| `.dockerignore` | -- | Excludes tests, docs, .git |
| `README.md` | Dev setup + versioning guide | Dev + Docker + versioning guide |
| **Git** | Initialized + first commit | Initialized + first commit |
| **GitHub** | Optionally creates repo via `gh` CLI | Optionally creates repo via `gh` CLI |

### Environment Variables (optional)

Override defaults when scaffolding:

```bash
CODEARTIFACT_DOMAIN=my-domain \
CODEARTIFACT_REPO=my-repo \
AWS_ACCOUNT_ID=123456789012 \
GITHUB_ORG=Aptos-Unified-Commerce \
./scp-ci-templates/create-repo.sh framework scp-auth-lib "Shared auth library"
```

---

## Quick Start (Existing Repos)

Already have a repo? Add `.github/workflows/ci.yml` — one file, same for both types:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    uses: Aptos-Unified-Commerce/scp-ci-templates/.github/workflows/ci-detect-and-build.yml@main
    with:
      package-name: my_package
      codeartifact-domain: my-domain
      codeartifact-repo: my-repo
      codeartifact-owner: "123456789012"
      ecr-repository: my-service          # Only needed for agent repos
    secrets:
      AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # Optional: AI analysis
```

The agent handles everything autonomously — detection, routing, healing, analytics.

---

## How the Agent Pipeline Works

### For Frameworks (no Dockerfile)

```
checkout → detect (framework) → uv sync → pytest → uv build → publish to CodeArtifact
                                              │
                                         [on failure]
                                              ↓
                                      diagnose → heal → retry (up to 2x)
```

### For Agents (has Dockerfile)

```
checkout → detect (agent) → configure CodeArtifact → uv sync → pytest → docker build → push to ECR
                                  │                                │            │
                                  │                           [on failure]  [on failure]
                              pull framework                      ↓            ↓
                              libs from                    heal + retry   no-cache retry
                              CodeArtifact
```

Key difference: Agent repos **do NOT contain a Dockerfile**. The Dockerfile is centrally managed in `scp-ci-templates/dockerfiles/agent.Dockerfile` and generated at runtime during CI.

### Centralized Dockerfile

The golden Dockerfile template lives in this repo and is injected into every agent build:

```
scp-ci-templates/dockerfiles/agent.Dockerfile  →  generated at CI runtime  →  builds agent code
```

**Benefits:**
- Update Python version, security hardening, or base image once → all agents get it
- Agent teams focus on application code, not Docker configuration
- Consistent image structure across all services

**Per-repo customization** via `.ci-agent.yml` (no Dockerfile editing needed):

```yaml
docker:
  python_version: "3.12"           # Base Python version (default: 3.11)
  port: 9000                       # Exposed port (default: 8000)
  entrypoint: '["gunicorn", "my_pkg.wsgi:app"]'  # Auto-detected if not set
  extra_system_packages:           # Runtime apt packages
    - libpq5
  extra_build_packages:            # Build-time apt packages
    - gcc
    - libpq-dev
```

If no `.ci-agent.yml` exists, the agent auto-detects the entrypoint from `pyproject.toml` + `src/{pkg}/main.py`.

---

## Autonomous Capabilities

### 1. Smart Detection

| What | How |
|------|-----|
| **Repo role** | Dockerfile present → agent; absent → framework |
| **Project type** | Marker files: `pyproject.toml`, `package.json`, `go.mod`, etc. |
| **Frameworks** | Dependency scanning: FastAPI, Flask, LangChain, Express, etc. |
| **Test tools** | Config detection: pytest, jest, go test, etc. |
| **Security** | Committed `.env`, hardcoded credentials, unpinned deps |

### 2. Self-Healing (10+ failure patterns)

| Failure | Strategy |
|---------|----------|
| Dependency conflict | Clear lockfile, retry |
| Flaky test | Retry failed only (`--lf`) |
| Network timeout | Extended timeouts |
| Rate limit | Backoff 30s |
| OOM | Reduce parallelism |
| Docker build failure | Retry without cache |
| Import error | Reinstall deps |
| Auth failure | Refresh credentials |

Up to **2 healing attempts** per build.

### 3. Semantic Versioning

Automatic version bumping based on [Conventional Commits](https://www.conventionalcommits.org/):

| Commit Prefix | Bump Type | Example |
|--------------|-----------|---------|
| `feat!:` / `BREAKING CHANGE:` | **major** | `feat!: remove legacy API` |
| `feat:` | **minor** | `feat: add auth module` |
| `fix:` / `chore:` / `docs:` / anything else | **patch** | `fix: handle null response` |

On push to `main`:
1. Version is computed from commits since last tag
2. Build + tests + security scan run
3. `pyproject.toml` is updated with the new version and committed back to `main`
4. Git tag `v{version}` is created

If `pyproject.toml` doesn't exist, it is **created automatically** starting at `0.0.1`. The tag and file version are always kept in sync.

### 4. Security Scanning

Integrated security scans run **in parallel** with builds on every CI run:

| Tool | What it scans | Category |
|------|-------------|----------|
| **pip-audit** | Python dependencies against OSV database | Vulnerabilities |
| **bandit** | Python source code (SAST) | Code security |
| **trivy** | Filesystem + Docker images | Vulnerabilities, secrets, misconfig |
| **hadolint** | Dockerfile best practices | Dockerfile linting |
| **gitleaks** | Code + git history for leaked secrets | Secret detection |

Results are:
- Aggregated into a unified report in GitHub Step Summary
- Uploaded as SARIF to GitHub Security tab
- Saved as a build artifact

Set `fail-on-high-severity: true` to block builds with critical/high findings.

**Snyk migration path:** When ready, add `SNYK_TOKEN` secret and the agent will use Snyk in place of pip-audit and trivy.

### 5. Build Analytics

- Tracks last 200 builds per branch
- Failure rate, build time trends, flaky test detection
- Healing effectiveness tracking
- Optimization recommendations

### 6. AI Analysis (Optional)

When `ANTHROPIC_API_KEY` is set → Claude analyzes failures and suggests fixes.

---

## Repository Structure

```
scp-ci-templates/
├── .github/workflows/
│   ├── ci-detect-and-build.yml      # Router: detects role, routes to framework or agent
│   ├── ci-framework.yml             # Framework: uv build → CodeArtifact
│   ├── ci-agent-service.yml         # Agent: docker build → ECR (pulls from CodeArtifact)
│   ├── ci-security.yml              # Security scanning (pip-audit, bandit, trivy, gitleaks)
│   └── ci-agent-analyze.yml         # Scheduled build analytics
├── agent/                           # Python CI Agent package
│   ├── src/ci_agent/
│   │   ├── cli.py                   # ci-agent detect|heal|analyze|version|security|record
│   │   ├── models.py               # BuildPlan, HealingAction, BuildRecord
│   │   ├── detect/                  # Detection: role, type, frameworks, security
│   │   ├── heal/                    # Self-healing: strategies, auto-fix PRs
│   │   ├── analyze/                 # Analytics: history, insights, optimizer
│   │   ├── version/                 # Semantic versioning from conventional commits
│   │   ├── security/                # Security scanning orchestrator (5 tools)
│   │   ├── docker/                  # Dockerfile generator from golden template
│   │   └── llm/                     # Optional Claude-powered analysis
│   └── tests/                       # 52 unit tests
├── dockerfiles/
│   └── agent.Dockerfile             # Golden Dockerfile template (centrally managed)
├── templates/                       # Repo scaffolding templates
│   ├── framework/                   # Library template (no Dockerfile)
│   │   ├── .github/workflows/ci.yml
│   │   ├── .gitignore
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── src/{{package_name}}/
│   │   └── tests/unit/
│   └── agent/                       # Service template (with Dockerfile)
│       ├── .github/workflows/ci.yml
│       ├── .gitignore
│       ├── pyproject.toml
│       ├── README.md
│       ├── src/{{package_name}}/    # FastAPI app with /health
│       └── tests/unit/
├── create-repo.sh                   # CLI scaffolder for new repos
├── docs/                            # Stakeholder documentation
├── examples/                        # Example caller workflows
└── README.md
```

---

## Override Detection

Place `.ci-agent.yml` in your repo root:

```yaml
# Force this repo to be treated as an agent (service)
repo_role: agent
project_type: python
frameworks:
  - fastapi
```

```yaml
# Force this repo to be treated as a framework (library)
repo_role: framework
project_type: python
```

---

## CLI Reference

```bash
pip install ./agent

# Detect repo role and generate build plan
ci-agent detect --repo-path /path/to/repo

# Compute next semantic version from conventional commits
ci-agent version --repo-path /path/to/repo
ci-agent version --repo-path /path/to/repo --apply   # Also update pyproject.toml

# Run security scans (uses all available tools)
ci-agent security --repo-path /path/to/repo
ci-agent security --repo-path /path/to/repo --image my-image:latest  # + Docker image scan
ci-agent security --repo-path /path/to/repo --fail-on-high           # Exit 1 on critical/high

# Diagnose a build failure
ci-agent heal --log-file /tmp/build.log --attempt 1

# Analyze build history
ci-agent analyze --history-file build_history.json

# Record a build result
ci-agent record --build-type framework --status success --duration 45.2
```

---

## AWS Prerequisites

### IAM Role Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CodeArtifact",
      "Effect": "Allow",
      "Action": [
        "codeartifact:GetAuthorizationToken",
        "codeartifact:GetRepositoryEndpoint",
        "codeartifact:PublishPackageVersion",
        "codeartifact:PutPackageMetadata",
        "sts:GetServiceBearerToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECR",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart"
      ],
      "Resource": "*"
    }
  ]
}
```

### Secrets (set at org level)

| Secret | Required | Description |
|--------|----------|-------------|
| `AWS_ROLE_ARN` | Yes | IAM role ARN with OIDC trust |
| `ANTHROPIC_API_KEY` | No | Enables AI-powered failure analysis |
