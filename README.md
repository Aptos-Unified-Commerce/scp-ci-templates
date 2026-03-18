# SCP CI Templates

Autonomous CI/CD platform for SCP services with smart detection, self-healing, and build analytics.

```
┌─────────────────────────────────────────────────────────┐
│                    Caller Repo CI                       │
│              (minimal .github/workflows/ci.yml)         │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              ci-detect-and-build.yml                     │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────┐  │
│  │   Detection   │──▶│   Routing    │──▶│   Build    │  │
│  │    Agent      │   │  (auto)      │   │  Pipeline  │  │
│  └──────────────┘   └──────────────┘   └─────┬──────┘  │
│                                               │         │
│                          ┌────────────────────┤         │
│                          ▼                    ▼         │
│                   ┌────────────┐      ┌────────────┐   │
│                   │  Healing   │      │  Analytics  │   │
│                   │   Agent    │      │    Agent    │   │
│                   └────────────┘      └────────────┘   │
│                                               │         │
│                          ┌────────────────────┤         │
│                          ▼                    ▼         │
│                   ┌────────────┐      ┌────────────┐   │
│                   │ CodeArtifact│     │    ECR      │   │
│                   └────────────┘      └────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Autonomous Capabilities

### 1. Smart Detection

The agent scans the caller repo and auto-detects:

| What | How |
|------|-----|
| **Project type** | Marker files: `pyproject.toml` (Python), `package.json` (Node), `go.mod` (Go), `Cargo.toml` (Rust), `pom.xml` (Java) |
| **Frameworks** | Dependency scanning: FastAPI, Flask, Django, Express, Next.js, Gin, LangChain, etc. |
| **Test tools** | Config detection: pytest, jest, vitest, go test, maven-surefire |
| **Deploy target** | Structure inference: Dockerfile → ECR, SAM/serverless → Lambda, library → CodeArtifact |
| **Security issues** | Committed `.env` files, hardcoded credentials, unpinned deps, Dockerfile anti-patterns |

Detection outputs a `BuildPlan` with a **confidence score** (0.0–1.0).

### 2. Self-Healing

When a build fails, the agent classifies the failure and applies a healing strategy:

| Failure Class | Pattern | Strategy |
|--------------|---------|----------|
| `dependency-conflict` | `ResolutionImpossible`, version conflicts | Clear lockfile, retry with relaxed resolution |
| `test-flaky` | Timeout in tests, intermittent failures | Retry failed tests only with `--lf` |
| `test-failure` | `FAILED tests/`, `AssertionError` | Retry test suite (max 1 retry) |
| `network-timeout` | `ETIMEDOUT`, `ConnectionResetError` | Retry with extended timeouts |
| `rate-limit` | HTTP 429, `Too Many Requests` | Backoff 30s and retry |
| `disk-space` | `ENOSPC`, `No space left` | Prune Docker/pip caches, retry |
| `auth-failure` | 401/403, `ExpiredToken` | Refresh credentials, retry |
| `oom` | `MemoryError`, `heap out of memory` | Reduce parallelism, retry |
| `docker-build-failure` | `executor failed running` | Retry without Docker cache |
| `import-error` | `ModuleNotFoundError` | Reinstall dependencies from scratch |

Each build gets up to **2 healing attempts**. If a failure is healed 3+ times across builds, the analyzer flags it for a permanent fix.

### 3. Build Analytics & Learning

The agent tracks build history (last 200 runs per branch) and produces:

- **Average build time** and trend (improving/stable/degrading)
- **Failure rate** and top failure classes
- **Flaky test detection** (branches that alternate success/failure)
- **Healing effectiveness** (success rate per strategy)
- **Optimization recommendations** (caching, parallelization, splitting jobs)

### 4. AI-Powered Analysis (Optional)

When `ANTHROPIC_API_KEY` is provided, the agent sends failure logs to Claude for:

- **Root cause analysis** of complex failures
- **Specific fix suggestions** with exact commands/code changes
- **Pipeline optimization recommendations** based on build history

Falls back to heuristic analysis when no API key is set.

---

## Repository Structure

```
scp-ci-templates/
├── .github/workflows/
│   ├── ci-detect-and-build.yml      # Smart router with agent-based detection
│   ├── ci-python.yml                # Python: uv build + test + self-healing + CodeArtifact
│   ├── ci-docker.yml                # Docker: build + self-healing + ECR push
│   └── ci-agent-analyze.yml         # Scheduled build analytics workflow
├── agent/                           # Python CI Agent package
│   ├── pyproject.toml
│   ├── src/ci_agent/
│   │   ├── cli.py                   # CLI: ci-agent detect|heal|analyze|record
│   │   ├── models.py                # BuildPlan, HealingAction, BuildRecord, AnalysisReport
│   │   ├── detect/                  # Detection modules
│   │   │   ├── detector.py          # Orchestrator
│   │   │   ├── project_type.py      # Language detection
│   │   │   ├── framework.py         # Framework detection
│   │   │   ├── test_tools.py        # Test tool detection
│   │   │   ├── deploy_target.py     # Deployment target inference
│   │   │   └── security.py          # Security scanning
│   │   ├── heal/                    # Self-healing modules
│   │   │   ├── healer.py            # Failure diagnosis
│   │   │   ├── strategies.py        # Pattern catalog (10+ failure types)
│   │   │   └── pr_creator.py        # Auto-fix PR creation
│   │   ├── analyze/                 # Analytics modules
│   │   │   ├── analyzer.py          # Report generation
│   │   │   ├── history.py           # Build history persistence
│   │   │   ├── insights.py          # Trend analysis, flaky test detection
│   │   │   └── optimizer.py         # Optimization recommendations
│   │   └── llm/
│   │       └── advisor.py           # Optional Claude-powered analysis
│   └── tests/                       # 23 unit tests
├── examples/
│   ├── caller-library.yml
│   └── caller-service.yml
└── README.md
```

---

## Quick Start — Calling from Your Repo

Create `.github/workflows/ci.yml` in your repo:

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
      ecr-repository: my-service          # Only needed if repo has a Dockerfile
    secrets:
      AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # Optional: enables AI analysis
```

The agent handles everything autonomously:
- Detects your project type, frameworks, and deploy target
- Runs tests and builds
- Self-heals on failure (up to 2 retries with different strategies)
- Tracks build history for analytics
- Publishes to CodeArtifact or ECR based on detection

---

## Override Detection with `.ci-agent.yml`

Place this in your repo root to override auto-detection:

```yaml
project_type: python
frameworks:
  - fastapi
deploy_target: ecr
suggested_workflow: ci-docker
test_tool: pytest
python_version: ">=3.11"
```

---

## CLI Reference

The agent is also usable as a standalone CLI:

```bash
# Install
pip install ./agent

# Detect project type and generate build plan
ci-agent detect --repo-path /path/to/repo

# Diagnose a build failure
ci-agent heal --log-file /tmp/build.log --attempt 1

# Analyze build history
ci-agent analyze --history-file build_history.json

# Record a build result
ci-agent record --build-type python --status success --duration 45.2
```

---

## Workflow Reference

### `ci-detect-and-build.yml` — Smart Router (Primary Entry Point)

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `package-name` | Yes | — | Python package name |
| `codeartifact-domain` | Yes | — | CodeArtifact domain |
| `codeartifact-repo` | Yes | — | CodeArtifact repository |
| `codeartifact-owner` | Yes | — | AWS account ID |
| `ecr-repository` | No | `""` | ECR repo (needed if Dockerfile exists) |
| `enable-healing` | No | `true` | Enable self-healing |
| `enable-analysis` | No | `true` | Enable build analytics |

| Secret | Required | Description |
|--------|----------|-------------|
| `AWS_ROLE_ARN` | Yes | IAM role for CodeArtifact/ECR |
| `ANTHROPIC_API_KEY` | No | Enables AI-powered failure analysis |

### `ci-python.yml` — Python Build with Self-Healing

Direct use for Python-only repos. Includes full healing loop (2 attempts), build history tracking, and CodeArtifact publishing.

### `ci-docker.yml` — Docker Build with Self-Healing

Direct use for Docker repos. Heals Docker build failures (cache invalidation, no-cache retry). Pushes to ECR with tags: `<sha>`, `<branch>`, `latest`.

### `ci-agent-analyze.yml` — Build Analytics

Run on schedule or on-demand to analyze build history and generate optimization reports.

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

### GitHub OIDC Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:Aptos-Unified-Commerce/*:*"
        }
      }
    }
  ]
}
```

### Secrets (set at org level)

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | IAM role ARN |
| `ANTHROPIC_API_KEY` | Optional — enables AI analysis |
