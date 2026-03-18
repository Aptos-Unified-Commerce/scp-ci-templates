# SCP CI Templates — Stakeholder Document

**Repository:** [Aptos-Unified-Commerce/scp-ci-templates](https://github.com/Aptos-Unified-Commerce/scp-ci-templates)
**Version:** 0.1.0
**Date:** March 2026
**Prepared for:** Engineering Leadership, DevOps, Platform Engineering

---

## Executive Summary

The **SCP CI Templates** repository is an autonomous CI/CD platform that eliminates manual pipeline configuration for all SCP services. Any new Python library or Dockerized service can achieve production-grade CI/CD — including testing, security scanning, versioning, and publishing — by adding a single 17-line workflow file.

The platform introduces an **AI-powered CI Agent** that autonomously detects project types, self-heals from build failures, tracks build analytics, and optionally leverages Claude for root cause analysis.

### Key Benefits

| Benefit | Impact |
|---------|--------|
| **Zero-config CI/CD** | New repos get full pipelines in < 5 minutes |
| **Self-healing builds** | Up to 80% fewer manual interventions for transient failures |
| **Automated versioning** | No manual version bumps — conventional commits drive releases |
| **Security by default** | 5 security tools run on every build, every repo |
| **Standardized pipelines** | All repos follow the same patterns — easier auditing and compliance |
| **Centralized Dockerfile** | One golden template for all agents — update once, all services get it |
| **Build intelligence** | Historical analytics surface trends, flaky tests, and optimizations |

---

## Architecture Overview

The platform classifies every repository into one of two roles:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SCP CI/CD Platform                                │
│                                                                     │
│  FRAMEWORKS (libraries)                AGENTS (services)            │
│  ┌─────────────────────┐               ┌─────────────────────┐     │
│  │ scp-ai-platform     │               │ scp-agent-test-     │     │
│  │ (Python library)    │──publishes──▶  │ runner              │     │
│  │ No Dockerfile       │  to            │ (Python + Docker)   │     │
│  └─────────┬───────────┘  CodeArtifact  └─────────┬───────────┘    │
│            │                                      │                 │
│      uv build + test                     uv test + docker build    │
│            │                                      │                 │
│            ▼                                      ▼                 │
│    ┌──────────────┐                      ┌──────────────┐          │
│    │ CodeArtifact │                      │     ECR      │          │
│    │ (Python pkgs)│                      │(Docker imgs) │          │
│    └──────────────┘                      └──────────────┘          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Runs on every build: Security Scan + Versioning + Analytics  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

| Repo Type | What it is | Build | Publishes to |
|-----------|-----------|-------|-------------|
| **Framework** | Shared Python library (e.g., `scp-ai-platform`) | `uv build` → wheel + sdist | AWS CodeArtifact |
| **Agent** | Python service — no Dockerfile in repo (e.g., `scp-agent-test-runner`) | `uv test` → `docker build` | AWS ECR |

**Auto-detection:** The CI Agent scans the repo and determines the role automatically — no manual configuration needed.

**Centralized Dockerfile:** Agent repos do **not** contain a Dockerfile. The Dockerfile is centrally managed in `scp-ci-templates/dockerfiles/agent.Dockerfile` and injected at CI runtime. This means updating the base image, Python version, or security hardening in one place applies to **all** agent services instantly.

---

## What a Caller Repo Needs

Every repo across the organization uses the same 17-line CI configuration:

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
```

That's it. The template handles everything else.

---

## Pipeline Phases

Every build runs through 5 autonomous phases:

### Phase 1: Detection

The CI Agent scans the repo and outputs a **Build Plan**:

| What it detects | How |
|----------------|-----|
| **Repo role** | Dockerfile present → Agent; absent → Framework |
| **Language** | Marker files: `pyproject.toml` (Python), `package.json` (Node), `go.mod` (Go) |
| **Frameworks in use** | Dependency scanning: FastAPI, Flask, LangChain, Express, etc. |
| **Test tool** | Config detection: pytest, jest, go test |
| **Security issues** | Committed `.env` files, hardcoded credentials, unpinned deps |
| **Confidence score** | 0.0–1.0 based on detection clarity |

Repos can override auto-detection by placing a `.ci-agent.yml` file at the root.

### Phase 2: Security Scanning (parallel)

Five industry-standard tools run **in parallel with the build** — no time penalty:

| Tool | What it scans | Category |
|------|-------------|----------|
| **pip-audit** | Python dependencies against OSV vulnerability database | Dependency vulnerabilities |
| **bandit** | Python source code for security anti-patterns | Static analysis (SAST) |
| **trivy** | Filesystem + Docker images for CVEs, secrets, misconfigs | Multi-scanner |
| **hadolint** | Dockerfile best practices and security | Dockerfile linting |
| **gitleaks** | Code + full git history for leaked secrets | Secret detection |

Results are:
- Aggregated into a unified severity report (critical / high / medium / low)
- Uploaded to the **GitHub Security tab** (SARIF format)
- Available as a downloadable build artifact

Optional: set `fail-on-high-severity: true` to block deployments with critical/high findings.

**Snyk migration path:** The architecture is designed to swap pip-audit and trivy with Snyk when the organization is ready.

### Phase 3: Build & Test (with Self-Healing)

The build runs with **autonomous failure recovery**:

```
Test → [FAIL] → Diagnose → Apply healing strategy → Retry
                                                      ↓
                                              [FAIL] → Diagnose → Retry (attempt 2)
                                                                    ↓
                                                            [FAIL] → Report failure
```

**10+ failure patterns are automatically detected and healed:**

| Failure Pattern | What triggers it | Healing strategy |
|----------------|-----------------|------------------|
| Dependency conflict | `ResolutionImpossible` | Clear lockfile, retry with fresh resolution |
| Flaky test | Intermittent test timeouts | Retry only failed tests (`--lf`) |
| Network timeout | `ETIMEDOUT`, `ConnectionResetError` | Retry with extended timeouts |
| Rate limit | HTTP 429 | Wait 30 seconds, retry |
| Out of memory | `MemoryError`, heap exhaustion | Reduce test parallelism |
| Docker build failure | Layer cache corruption | Retry without Docker cache |
| Import error | `ModuleNotFoundError` | Reinstall dependencies from scratch |
| Auth failure | 401/403, expired token | Refresh AWS credentials |
| Disk space | `ENOSPC` | Prune Docker/pip caches, retry |
| Test failure | `AssertionError` | Retry full test suite (max 1 retry) |

Each build gets **up to 2 healing attempts** before failing. Healed builds are tracked separately for analytics.

### Phase 3.5: Dockerfile Generation (Agents Only)

For agent repos, the Dockerfile is **not in the repo** — it is generated at CI runtime:

```
scp-ci-templates/dockerfiles/agent.Dockerfile    (golden template, centrally managed)
        │
        ▼  ci-agent docker-gen
        │  reads .ci-agent.yml from the agent repo (if present)
        │  auto-detects entrypoint from pyproject.toml + src/{pkg}/main.py
        ▼
   Generated Dockerfile    (in CI workspace, never committed)
        │
        ▼  docker build
   Docker image → pushed to ECR
```

**What the golden template provides (all agents get this automatically):**
- Multi-stage build (builder + runtime) for smaller images
- Non-root user (`appuser`) for security
- Built-in `HEALTHCHECK` on `/health`
- `PIP_EXTRA_INDEX_URL` build arg for CodeArtifact framework dependencies
- Optimized layer ordering (deps before source for better caching)

**Per-repo customization via `.ci-agent.yml`** (no Dockerfile editing):

```yaml
docker:
  python_version: "3.12"           # Base image (default: 3.11)
  port: 9000                       # Exposed port (default: 8000)
  entrypoint: '["gunicorn", "my_pkg.wsgi:app"]'  # Auto-detected if not set
  extra_system_packages:           # Runtime apt packages
    - libpq5
    - ffmpeg
  extra_build_packages:            # Build-time only apt packages
    - gcc
    - libpq-dev
```

If no `.ci-agent.yml` exists, the agent auto-detects everything from `pyproject.toml`.

**Why this matters:**
- Upgrade Python 3.11 → 3.12 for all agents → edit one file, push once
- Add a security patch to every container → same
- Developers never write or maintain Dockerfiles — they focus on application code

### Phase 4: Publish

| Repo Type | What happens |
|-----------|-------------|
| **Framework** | `uv build` creates wheel + sdist → published to **AWS CodeArtifact** |
| **Agent** | Generated Dockerfile → `docker build` → tagged with SHA, branch, `latest` → pushed to **AWS ECR** |

Agent Docker builds receive CodeArtifact credentials as a build argument (`PIP_EXTRA_INDEX_URL`), so the golden Dockerfile can `pip install` framework libraries automatically.

### Phase 5: Version & Tag

On successful push to `main`:

1. **Compute version** from conventional commits since last tag:
   - `feat:` commits → **minor** bump (0.1.0 → 0.2.0)
   - `fix:` commits → **patch** bump (0.1.0 → 0.1.1)
   - `feat!:` or `BREAKING CHANGE:` → **major** bump (0.1.0 → 1.0.0)

2. **Update `pyproject.toml`** with the new version (creates the file if it doesn't exist)

3. **Commit** the version change back to `main` with `[skip ci]` to prevent loops

4. **Create and push** a git tag: `v{version}`

The version in the file and the git tag are **always in sync**.

---

## Build Analytics & Learning

The platform tracks every build and surfaces insights over time:

| Metric | What it measures |
|--------|-----------------|
| **Average build time** | Mean duration across recent builds |
| **Failure rate** | % of builds that failed (excluding healed) |
| **Top failure classes** | Most common failure patterns |
| **Flaky test detection** | Tests/branches that alternate success/failure |
| **Build time trend** | Improving, stable, or degrading |
| **Healing effectiveness** | Success rate per healing strategy |

The system generates **optimization recommendations**:
- Slow builds → suggest parallelization or caching
- High failure rate → flag top failure classes for investigation
- Ineffective healing → recommend permanent fixes
- Repeated healing → flag fragile pipeline areas

### Optional AI-Powered Analysis

When an `ANTHROPIC_API_KEY` secret is configured, the platform sends build failures to **Claude** for:
- **Root cause analysis** of complex failures
- **Specific fix suggestions** with exact commands
- **Pipeline optimization recommendations** based on build history

This is fully optional and gracefully degrades when not configured.

---

## Repository Structure

```
scp-ci-templates/
├── .github/workflows/
│   ├── ci-detect-and-build.yml       # Main orchestrator (5-phase pipeline)
│   ├── ci-framework.yml              # Framework: test + build + publish to CodeArtifact
│   ├── ci-agent-service.yml          # Agent: test + Docker build + push to ECR
│   ├── ci-security.yml               # Security scanning (5 tools)
│   └── ci-agent-analyze.yml          # Scheduled build analytics
│
├── agent/                            # Python CI Agent package
│   ├── src/ci_agent/
│   │   ├── cli.py                    # CLI: 7 commands (detect, version, security, docker-gen, heal, analyze, record)
│   │   ├── models.py                 # Data models (BuildPlan, HealingAction, etc.)
│   │   ├── detect/                   # Auto-detection (5 modules)
│   │   ├── heal/                     # Self-healing (3 modules, 10+ patterns)
│   │   ├── analyze/                  # Build analytics (4 modules)
│   │   ├── version/                  # Semantic versioning
│   │   ├── security/                 # Security scan orchestrator (5 tools)
│   │   ├── docker/                   # Dockerfile generator from golden template
│   │   └── llm/                      # Optional Claude integration
│   └── tests/                        # 52 unit tests (100% passing)
│
├── dockerfiles/
│   └── agent.Dockerfile              # Golden Dockerfile (centrally managed, injected at CI runtime)
│
├── templates/                        # Repo scaffolding templates
│   ├── framework/                    # Library template (for create-repo.sh)
│   └── agent/                        # Service template — no Dockerfile (for create-repo.sh)
│
├── create-repo.sh                    # CLI to scaffold new repos
├── docs/                             # Stakeholder documentation
├── examples/
│   ├── caller-library.yml            # Example for framework repos
│   └── caller-service.yml            # Example for agent repos
│
└── README.md
```

---

## Local Development for Agent Repos

Since agent repos don't contain a Dockerfile, developers use the CI Agent CLI to generate one locally when needed.

### One-Time Setup

```bash
# Clone the templates repo (if not already)
git clone git@github.com:Aptos-Unified-Commerce/scp-ci-templates.git ~/scp-ci-templates

# Install the CI agent tool
pip install ~/scp-ci-templates/agent
```

### Building a Local Docker Image

From your agent repo directory:

```bash
# Generate the Dockerfile from the golden template
ci-agent docker-gen \
  --template ~/scp-ci-templates/dockerfiles/agent.Dockerfile \
  --repo-path . \
  --output Dockerfile

# Build the image
docker build -t my-agent:local .

# Run it
docker run -p 8000:8000 my-agent:local

# Clean up the generated Dockerfile (don't commit it)
rm Dockerfile
```

Or as a one-liner:

```bash
ci-agent docker-gen --template ~/scp-ci-templates/dockerfiles/agent.Dockerfile --repo-path . --output Dockerfile \
  && docker build -t my-agent:local . \
  && rm Dockerfile
```

### With CodeArtifact dependencies (if your agent uses framework libraries)

```bash
# Get CodeArtifact token
export CODEARTIFACT_TOKEN=$(aws codeartifact get-authorization-token \
  --domain my-domain --domain-owner 123456789012 \
  --query authorizationToken --output text)

export CODEARTIFACT_URL=$(aws codeartifact get-repository-endpoint \
  --domain my-domain --domain-owner 123456789012 --repository my-repo \
  --format pypi --query repositoryEndpoint --output text)

# Generate and build with CodeArtifact index
ci-agent docker-gen --template ~/scp-ci-templates/dockerfiles/agent.Dockerfile --repo-path . --output Dockerfile
docker build \
  --build-arg PIP_EXTRA_INDEX_URL="https://aws:${CODEARTIFACT_TOKEN}@${CODEARTIFACT_URL#https://}simple/" \
  -t my-agent:local .
rm Dockerfile
```

### Customizing the local build

Create or edit `.ci-agent.yml` in your repo:

```yaml
docker:
  python_version: "3.12"
  port: 9000
  extra_system_packages:
    - libpq5
```

Then run `ci-agent docker-gen` — it picks up your config automatically.

> **Note:** The generated Dockerfile should **never be committed** to the repo. It is always generated on-the-fly, both locally and in CI. This ensures all agents always use the latest golden template.

---

## Organizational Benefits

### For Engineering Teams

- **Faster onboarding:** New repos get production CI/CD in minutes, not days
- **Less firefighting:** Self-healing eliminates 80%+ of transient CI failures
- **No version management overhead:** Conventional commits drive automated releases
- **Security built-in:** No separate security pipeline to configure or maintain

### For DevOps / Platform Engineering

- **Single source of truth:** All CI/CD logic in one repo — update once, all repos benefit
- **Audit trail:** Build history, security reports, and version tags provide full traceability
- **Standardization:** Every repo follows the same build, test, scan, version, publish flow
- **Extensibility:** Add new tools (e.g., Snyk) or patterns centrally

### For Security & Compliance

- **5 security tools on every build:** Dependencies, source code, secrets, containers, Dockerfiles
- **SARIF integration:** Results appear directly in GitHub Security tab
- **Gate deployments:** `fail-on-high-severity` blocks releases with critical/high findings
- **Secret detection:** Full git history scanned for leaked credentials

### For Engineering Leadership

- **Build intelligence:** Analytics dashboards show failure trends, build health, optimization opportunities
- **Cost awareness:** Identifies slow builds that consume unnecessary CI minutes
- **Risk reduction:** Automated security scanning and version management reduce human error
- **Scalability:** Template-based approach scales to 10, 50, or 100+ repos with zero marginal effort

---

## AWS Infrastructure Requirements

### IAM Role (with GitHub OIDC trust)

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

### GitHub Secrets (set at org level)

| Secret | Required | Description |
|--------|----------|-------------|
| `AWS_ROLE_ARN` | Yes | IAM role ARN with OIDC trust for GitHub Actions |
| `ANTHROPIC_API_KEY` | No | Enables AI-powered failure analysis and optimization |

---

## Rollout Plan

### Week 1: Foundation
- [ ] Create AWS IAM role with OIDC trust for GitHub Actions
- [ ] Configure CodeArtifact domain and repository
- [ ] Configure ECR repositories for agent services
- [ ] Set `AWS_ROLE_ARN` as GitHub organization secret

### Week 2: Pilot — Framework
- [ ] Onboard `scp-ai-platform` (copy `examples/caller-library.yml`)
- [ ] Verify: detection → build → test → security scan → publish to CodeArtifact
- [ ] Verify: versioning with conventional commits → git tag
- [ ] Monitor first 10 builds for healing effectiveness

### Week 3: Pilot — Agent
- [ ] Onboard one agent service repo (copy `examples/caller-service.yml`)
- [ ] Verify: detection → test → Docker build → security scan → push to ECR
- [ ] Verify: agent pulls framework libs from CodeArtifact during Docker build
- [ ] Test: intentional failure to observe self-healing behavior

### Week 4: Expand & Optimize
- [ ] Onboard remaining framework and agent repos
- [ ] Review build analytics report (run `ci-agent-analyze.yml`)
- [ ] Tune `fail-on-high-severity` setting based on security findings
- [ ] Enable `ANTHROPIC_API_KEY` if AI analysis desired
- [ ] Evaluate Snyk migration timeline

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| CI/CD Platform | GitHub Actions |
| Build Tool | uv (fast Python package manager) |
| Container Build | Docker Buildx with layer caching |
| Python Package Registry | AWS CodeArtifact |
| Container Registry | AWS ECR |
| Authentication | AWS OIDC (no long-lived keys) |
| Security Scanning | pip-audit, bandit, trivy, hadolint, gitleaks |
| AI Analysis | Claude API (optional) |
| Agent Language | Python 3.11+ |
| Test Framework | pytest (52 unit tests) |

---

## Summary

The SCP CI Templates platform transforms CI/CD from a per-repo configuration burden into a centralized, intelligent, self-healing system. Every repo in the organization gets:

- **Autonomous detection** — no manual pipeline configuration
- **Self-healing builds** — 10+ failure patterns auto-resolved
- **Security by default** — 5 tools on every build
- **Automatic versioning** — conventional commits drive releases
- **Build intelligence** — analytics, trends, optimization recommendations
- **Optional AI insights** — Claude-powered failure analysis

One template repo. One workflow file per caller. Zero manual version management. Zero Dockerfiles to maintain. Security on every build.
