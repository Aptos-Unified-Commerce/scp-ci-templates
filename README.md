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

## Quick Start

Create `.github/workflows/ci.yml` in your repo — one file, same for both types:

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

Key difference: Agent builds pass `PIP_EXTRA_INDEX_URL` as a Docker build arg so the Dockerfile can `pip install` framework libraries from CodeArtifact.

**Agent Dockerfile example:**
```dockerfile
FROM python:3.11-slim
ARG PIP_EXTRA_INDEX_URL
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

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

### 3. Build Analytics

- Tracks last 200 builds per branch
- Failure rate, build time trends, flaky test detection
- Healing effectiveness tracking
- Optimization recommendations

### 4. AI Analysis (Optional)

When `ANTHROPIC_API_KEY` is set → Claude analyzes failures and suggests fixes.

---

## Repository Structure

```
scp-ci-templates/
├── .github/workflows/
│   ├── ci-detect-and-build.yml      # Router: detects role, routes to framework or agent
│   ├── ci-framework.yml             # Framework: uv build → CodeArtifact
│   ├── ci-agent-service.yml         # Agent: docker build → ECR (pulls from CodeArtifact)
│   └── ci-agent-analyze.yml         # Scheduled build analytics
├── agent/                           # Python CI Agent package
│   ├── src/ci_agent/
│   │   ├── cli.py                   # ci-agent detect|heal|analyze|record
│   │   ├── models.py               # BuildPlan, HealingAction, BuildRecord
│   │   ├── detect/                  # Detection: role, type, frameworks, security
│   │   ├── heal/                    # Self-healing: strategies, auto-fix PRs
│   │   ├── analyze/                 # Analytics: history, insights, optimizer
│   │   └── llm/                     # Optional Claude-powered analysis
│   └── tests/                       # 24 unit tests
├── examples/
│   ├── caller-library.yml           # Example for framework repos
│   └── caller-service.yml           # Example for agent repos
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
