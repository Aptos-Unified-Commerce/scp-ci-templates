# SCP CI/CD Platform — Complete Reference

**Repository:** [scp-ci-templates](https://github.com/Aptos-Unified-Commerce/scp-ci-templates)
**Last Updated:** March 2026

---

## 1. What is this?

The SCP CI/CD Platform is a centralized, autonomous build system for all SCP repositories. It lives in a single repo (`scp-ci-templates`) and provides everything needed to build, test, secure, version, and publish any Python library or service across the organization.

A developer creates a new repo, adds one small config file, and gets a full production-grade pipeline — detection, testing, security scanning, self-healing, versioning, and publishing — with zero manual setup.

---

## 2. The Two Repo Types

Every repository in the SCP ecosystem falls into one of two categories:

### Frameworks (Libraries)

Shared Python libraries that other services depend on.

- **Example:** `scp-ai-platform` (LLM clients, guardrails, tracing)
- **No Dockerfile** in the repo
- **Build output:** Python wheel + sdist package
- **Published to:** AWS CodeArtifact
- **Consumers:** Agent repos install these via `pip install`

### Agents (Services)

Python microservices that run as containers and use framework libraries.

- **Example:** `scp-agent-test-runner`, `scp-agent-orders`
- **No Dockerfile in the repo** — the Dockerfile is centrally managed (see Section 8)
- **Build output:** Docker image
- **Published to:** AWS ECR
- **Dependencies:** Pull framework libraries from CodeArtifact during Docker build

### How the platform tells them apart

| Signal | Classification |
|--------|---------------|
| Repo has `pyproject.toml` but no `Dockerfile` | Framework |
| Repo has `pyproject.toml` and a `Dockerfile` marker (via `.ci-agent.yml`) | Agent |
| Override via `.ci-agent.yml` with `repo_role: agent` or `repo_role: framework` | Manual override |

---

## 3. What Happens When You Push Code

Every push to any repo using this platform triggers the following pipeline:

```
Push / PR
   │
   ▼
Phase 1: DETECTION
   │  ci-agent detect
   │  → Scans repo files
   │  → Identifies: role (framework/agent), language, frameworks, test tool
   │  → Outputs a BuildPlan with confidence score
   │
   ├─────────────────────────────────┐
   ▼                                 ▼
Phase 2: SECURITY SCAN          Phase 3: BUILD & TEST
   │  (runs in parallel)            │
   │  pip-audit                     │  uv sync --all-extras
   │  bandit                        │  uv run pytest
   │  trivy                         │  uv build (framework)
   │  hadolint                      │  ── or ──
   │  gitleaks                      │  docker-gen + docker build (agent)
   │                                │
   │                                │  [on failure] → SELF-HEALING
   │                                │     diagnose → apply fix → retry
   │                                │     (up to 2 attempts)
   │                                │
   ▼                                ▼
Phase 4: PUBLISH (main branch only)
   │  Framework → uv publish → CodeArtifact
   │  Agent → docker push → ECR
   │
   ▼
Phase 5: VERSION & TAG (main branch only)
   │  Analyze commits since last tag
   │  Compute new version (semver)
   │  Update pyproject.toml
   │  Commit version bump
   │  Create git tag v{version}
```

---

## 4. Detection — How the Agent Analyzes Your Repo

When the pipeline starts, the CI Agent runs `ci-agent detect` which scans the repository and produces a **BuildPlan**.

### What it detects

| Category | What it looks for | How |
|----------|------------------|-----|
| **Repo role** | Framework or Agent | Presence of Dockerfile or `.ci-agent.yml` override |
| **Language** | Python, Node.js, Go, Rust, Java | Marker files: `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml` |
| **Frameworks** | FastAPI, Flask, Django, LangChain, Express, etc. | Scans dependency lists in `pyproject.toml`, `package.json`, `go.mod` |
| **Test tool** | pytest, jest, go test, etc. | Looks for `[tool.pytest]` in pyproject.toml, `jest.config.*`, `_test.go` files |
| **Python version** | `>=3.11` etc. | Reads `requires-python` from `pyproject.toml` |
| **Security issues** | Leaked secrets, sensitive files, unpinned deps | Regex scanning of source files, checks for `.env`, `*.pem`, `*.key` |
| **Confidence** | 0.0 to 1.0 | Based on how many signals were found |

### Example detection output

For `scp-ai-platform`:
```
Role:       framework
Language:   python
Frameworks: langchain
Test tool:  pytest
Python:     >=3.11
Target:     codeartifact
Workflow:   ci-framework
Confidence: 1.0
Warning:    Hardcoded credential in tests/unit/test_agent_invoker_tool.py
```

### Override detection

Place `.ci-agent.yml` in the repo root:

```yaml
repo_role: agent          # force agent even without Dockerfile
project_type: python
frameworks:
  - fastapi
```

---

## 5. Building — How Each Repo Type Gets Built

### Framework Build

```
1. uv sync --all-extras          Install all dependencies (runtime + test)
2. uv run pytest                 Run the test suite
3. uv build                      Create wheel (.whl) and sdist (.tar.gz) in dist/
```

**Output:** `dist/scp_ai_platform-0.2.0-py3-none-any.whl`

### Agent Build

```
1. Configure CodeArtifact        Set up pip index URL so framework libs can be installed
2. uv sync --all-extras          Install deps (including framework libs from CodeArtifact)
3. uv run pytest                 Run the test suite
4. ci-agent docker-gen            Generate Dockerfile from golden template
5. docker build                  Build the container image
```

**Output:** Docker image `123456789012.dkr.ecr.us-east-1.amazonaws.com/scp-agent-orders:abc1234`

The Dockerfile is never in the agent repo — it is generated at runtime from the centrally managed golden template (see Section 8).

---

## 6. Self-Healing — How the Agent Recovers from Failures

When a build step fails, the CI Agent reads the build log, classifies the failure, and applies a targeted fix before retrying.

### How it works

```
Step fails → ci-agent heal reads the log
           → Matches against 10+ known failure patterns
           → Returns: what failed, what to do, retry commands
           → Pipeline applies the fix and retries
           → Up to 2 retry attempts per build
```

### Known failure patterns

| What failed | How the agent detects it | What it does |
|------------|------------------------|-------------|
| **Dependency conflict** | Log contains `ResolutionImpossible`, version conflicts | Deletes lockfile, retries with fresh dependency resolution |
| **Flaky test** | Test failures with `timeout`, `intermittent` keywords | Retries only the failed tests with `pytest --lf` |
| **Test failure** | `FAILED tests/`, `AssertionError` | Retries the full test suite once |
| **Network timeout** | `ETIMEDOUT`, `ConnectionResetError`, `ReadTimeoutError` | Sets `PIP_TIMEOUT=120` and retries |
| **Rate limit** | HTTP `429`, `Too Many Requests` | Waits 30 seconds, then retries |
| **Out of memory** | `MemoryError`, `Killed`, `heap out of memory` | Reduces test parallelism, increases Node heap |
| **Disk space** | `No space left on device`, `ENOSPC` | Prunes Docker and pip caches, retries |
| **Auth failure** | `401 Unauthorized`, `403 Forbidden`, `ExpiredToken` | Flags for credential refresh, retries |
| **Docker build failure** | `executor failed running`, layer errors | Retries Docker build without cache |
| **Import error** | `ModuleNotFoundError`, `ImportError` | Deletes `.venv`, reinstalls all dependencies |
| **Unknown** | No pattern matches | Does not retry — reports failure immediately |

### What gets tracked

Every healing action is recorded in build history:
- Which failure pattern was detected
- Which strategy was applied
- Whether the retry succeeded
- The analytics module later reports which strategies are effective and which indicate a permanent issue

---

## 7. Versioning — How Versions Are Managed

Versions are **never manually edited**. They are computed automatically from commit messages using [Conventional Commits](https://www.conventionalcommits.org/).

### How developers control versions

| Commit message | Version bump | Example |
|---------------|-------------|---------|
| `feat: add new LLM provider` | **Minor** | 0.1.0 → 0.2.0 |
| `fix: handle null response` | **Patch** | 0.1.0 → 0.1.1 |
| `chore: update dependencies` | **Patch** | 0.1.0 → 0.1.1 |
| `docs: update README` | **Patch** | 0.1.0 → 0.1.1 |
| `feat!: remove legacy API` | **Major** | 0.1.0 → 1.0.0 |
| Commit message contains `BREAKING CHANGE:` | **Major** | 0.1.0 → 1.0.0 |

### What happens on push to main

```
1. ci-agent version reads pyproject.toml          → current version: 0.1.0
2. git log since last tag                          → 3 commits: 1 feat, 2 fix
3. Classify: feat present                          → minor bump
4. Compute: 0.1.0 → 0.2.0
5. Build + test + security all pass
6. ci-agent version --apply                        → writes "0.2.0" into pyproject.toml
7. git commit "chore(release): bump to 0.2.0 [skip ci]"
8. git tag v0.2.0
9. git push (commit + tag)
```

### Edge cases handled

| Scenario | What happens |
|----------|-------------|
| No `pyproject.toml` exists | Creates one with name from directory, version `0.0.1` |
| `pyproject.toml` exists but no `version` field | Injects `version = "X.Y.Z"` into the file |
| No commits since last tag | No version bump, no tag |
| Version commit triggers CI again | Prevented — commit message contains `[skip ci]` |

### What stays in sync

The version appears in exactly two places, always matching:
- `pyproject.toml` → `version = "0.2.0"`
- Git tag → `v0.2.0`

---

## 8. Centralized Dockerfile — How Agent Images Are Built

Agent repos **do not contain a Dockerfile**. The Dockerfile is owned and managed centrally in `scp-ci-templates/dockerfiles/agent.Dockerfile`.

### Why

| Problem with Dockerfiles in each repo | How centralization solves it |
|---------------------------------------|------------------------------|
| Teams copy-paste Dockerfiles, they drift | One golden template, always consistent |
| Python upgrade requires updating 20 repos | Edit one file, all agents get it next build |
| Security fix (e.g., non-root user) missed in some repos | Applied centrally to every agent |
| Developers spend time maintaining Docker configs | Developers write application code only |

### How it works at build time

```
scp-ci-templates repo                     Agent repo (e.g., scp-agent-orders)
├── dockerfiles/                          ├── src/scp_agent_orders/
│   └── agent.Dockerfile  ─── CI ───▶    │   ├── __init__.py
│       (golden template)    generates    │   └── main.py
│                            Dockerfile   ├── pyproject.toml
│                                         ├── .ci-agent.yml (optional)
│                                         └── .github/workflows/ci.yml
```

1. CI checks out both the agent repo and scp-ci-templates
2. Runs `ci-agent docker-gen` which reads the golden template
3. Reads `.ci-agent.yml` from the agent repo (if present) for customization
4. Auto-detects entrypoint from `pyproject.toml` + `src/{pkg}/main.py`
5. Writes the final `Dockerfile` to the CI workspace (never committed)
6. `docker build` uses the generated Dockerfile

### What the golden template provides (every agent gets this)

- **Multi-stage build** — builder stage for compiling, slim runtime stage
- **Non-root user** — `appuser` with UID 1001 for security
- **Health check** — built-in `HEALTHCHECK` hitting `/health` every 30s
- **CodeArtifact support** — `PIP_EXTRA_INDEX_URL` build arg for framework dependencies
- **Optimized layers** — dependencies installed before source code for better caching

### How a team customizes their build

Create `.ci-agent.yml` in the agent repo root:

```yaml
docker:
  python_version: "3.12"           # Base Python image (default: 3.11)
  port: 9000                       # Exposed port (default: 8000)
  entrypoint: '["gunicorn", "my_pkg.wsgi:app"]'  # Default: auto-detected uvicorn
  extra_system_packages:           # Runtime apt packages
    - libpq5
    - ffmpeg
  extra_build_packages:            # Build-time only apt packages
    - gcc
    - libpq-dev
```

If `.ci-agent.yml` is not present, everything is auto-detected.

### How a developer builds locally

```bash
# One-time: install the ci-agent tool
pip install path/to/scp-ci-templates/agent

# Generate Dockerfile + build image
ci-agent docker-gen \
  --template path/to/scp-ci-templates/dockerfiles/agent.Dockerfile \
  --repo-path . \
  --output Dockerfile

docker build -t my-agent:local .
docker run -p 8000:8000 my-agent:local

# Clean up (never commit the generated Dockerfile)
rm Dockerfile
```

If the agent uses framework libraries from CodeArtifact:

```bash
# Get auth token
TOKEN=$(aws codeartifact get-authorization-token \
  --domain my-domain --domain-owner 123456789012 \
  --query authorizationToken --output text)
URL=$(aws codeartifact get-repository-endpoint \
  --domain my-domain --domain-owner 123456789012 --repository my-repo \
  --format pypi --query repositoryEndpoint --output text)

# Build with CodeArtifact access
docker build --build-arg PIP_EXTRA_INDEX_URL="https://aws:${TOKEN}@${URL#https://}simple/" \
  -t my-agent:local .
```

---

## 9. Security Scanning — What Gets Checked

Security scans run **in parallel with the build** on every push and PR — they add no extra wait time.

### Tools and what they find

| Tool | What it scans | What it catches | Example finding |
|------|-------------|----------------|-----------------|
| **pip-audit** | Python dependencies | Known CVEs in packages you depend on | `requests 2.28.0 has CVE-2023-XXXX — upgrade to 2.31.0` |
| **bandit** | Python source code | Security anti-patterns (SQL injection, hardcoded passwords, unsafe eval) | `B608: Possible SQL injection via string formatting in query.py:45` |
| **trivy** | Filesystem + Docker images | CVEs in OS packages, Python deps, leaked secrets, IaC misconfigs | `libssl3 1.1.1 has CVE-2024-XXXX (CRITICAL)` |
| **hadolint** | Dockerfile | Best practice violations (runs as root, unpinned base image) | `DL3007: Using latest is prone to errors` |
| **gitleaks** | Code + full git history | Leaked API keys, passwords, tokens, private keys | `AWS Access Key detected in config.py (committed 3 months ago)` |

### Severity levels

| Level | What it means | Action |
|-------|-------------|--------|
| **Critical** | Actively exploited or trivially exploitable | Must fix before release |
| **High** | Serious vulnerability with known exploit path | Should fix before release |
| **Medium** | Vulnerability that requires specific conditions | Fix in next sprint |
| **Low** | Minor issue or informational | Track for later |

### Where results appear

1. **GitHub Step Summary** — unified table in the build output
2. **GitHub Security tab** — SARIF format, browsable per-file
3. **Build artifact** — downloadable JSON report (`security-report.json`)

### Blocking deployments

Set `fail-on-high-severity: true` in the workflow config to prevent publishing if any critical or high severity findings exist.

### Future: Snyk

The architecture is designed so that when the organization adopts Snyk, it replaces pip-audit and trivy with a single `SNYK_TOKEN` secret. The rest of the pipeline stays the same.

---

## 10. Build Analytics — What Gets Tracked

The platform records every build and surfaces patterns over time.

### What is tracked per build

| Field | Example |
|-------|---------|
| Run ID | `12345` |
| Timestamp | `2026-03-18T14:30:00Z` |
| Branch | `main` |
| Commit SHA | `abc1234` |
| Build type | `framework` or `agent` |
| Duration | `87.3 seconds` |
| Status | `success`, `failure`, or `healed` |
| Failure class | `dependency-conflict` (if failed) |
| Healing strategy | `clear-lockfile-retry` (if healed) |
| Healing success | `true` or `false` |

### Insights computed

| Metric | What it tells you |
|--------|------------------|
| **Average build time** | Are builds getting slower? |
| **Failure rate** | What % of builds fail (not counting healed)? |
| **Top failure classes** | What breaks most often? |
| **Flaky test detection** | Which branches alternate between pass and fail? |
| **Build time trend** | Improving, stable, or degrading over last 20 builds |
| **Healing effectiveness** | Which healing strategies actually work? |

### Recommendations generated

The analyzer produces actionable suggestions:

- Build time > 5 min → "Consider parallelizing tests or enabling caching"
- Build time > 10 min → "Split into separate test and build jobs"
- Healing strategy < 30% success → "This issue needs a permanent fix, not retries"
- Failure rate > 30% → "Investigate the top failure classes"
- 5+ healed builds → "These fragile areas need permanent fixes"

### Storage

Build history is stored as a JSON file (last 200 records per branch) in the CI cache. No database or external service required.

---

## 11. Creating New Repos — The Scaffolder

Teams create new repos using the `create-repo.sh` CLI:

### Creating a framework (library)

```bash
./scp-ci-templates/create-repo.sh framework scp-auth-lib "Shared authentication library"
```

**Generates:**

```
scp-auth-lib/
├── .github/workflows/ci.yml      Pre-configured pipeline (calls shared template)
├── .gitignore                     Python defaults
├── pyproject.toml                 Package config, version 0.0.1, pytest setup
├── README.md                     Dev setup + versioning guide
├── src/scp_auth_lib/__init__.py   Package entry point
├── tests/unit/test_placeholder.py Import test
└── .git/                          Initialized with first commit
```

### Creating an agent (service)

```bash
./scp-ci-templates/create-repo.sh agent scp-agent-orders "Order processing agent"
```

**Generates:**

```
scp-agent-orders/
├── .github/workflows/ci.yml      Pre-configured pipeline (calls shared template, includes ECR)
├── .gitignore                     Python defaults
├── pyproject.toml                 Service config with FastAPI, version 0.0.1
├── README.md                     Dev + Docker guide
├── src/scp_agent_orders/
│   ├── __init__.py
│   └── main.py                   FastAPI app with /health endpoint
├── tests/unit/test_health.py     Health endpoint test
└── .git/                          Initialized with first commit
```

**No Dockerfile** — it's generated at CI runtime from the golden template.

### Optional: auto-create on GitHub

If `gh` CLI is installed, the script prompts to create the GitHub repo and push:

```
Create GitHub repo at Aptos-Unified-Commerce/scp-agent-orders? (y/N) y
Repo created: https://github.com/Aptos-Unified-Commerce/scp-agent-orders
```

### Customizing defaults

```bash
CODEARTIFACT_DOMAIN=my-domain \
CODEARTIFACT_REPO=python-packages \
AWS_ACCOUNT_ID=123456789012 \
./scp-ci-templates/create-repo.sh agent scp-agent-orders "Order processing agent"
```

---

## 12. Publishing — Where Artifacts Go

### Framework artifacts → CodeArtifact

| What | Where |
|------|-------|
| `scp_ai_platform-0.2.0-py3-none-any.whl` | `my-domain/my-repo/scp_ai_platform/0.2.0/` |
| `scp_ai_platform-0.2.0.tar.gz` | `my-domain/my-repo/scp_ai_platform/0.2.0/` |

Other services install with:
```bash
aws codeartifact login --tool pip --domain my-domain --repository my-repo --domain-owner 123456789012
pip install scp-ai-platform
```

### Agent images → ECR

| What | Where |
|------|-------|
| `scp-agent-orders:abc1234` | `123456789012.dkr.ecr.us-east-1.amazonaws.com/scp-agent-orders:abc1234` |
| `scp-agent-orders:main` | Same, tagged with branch |
| `scp-agent-orders:latest` | Same, latest on main |
| `scp-agent-orders:v0.2.0` | Same, if version tag applied |

### When publishing happens

- **PR builds:** Test + scan only — nothing is published
- **Push to main:** Test + scan + publish + version tag

---

## 13. AI-Powered Analysis (Optional)

When the `ANTHROPIC_API_KEY` secret is configured, the platform can send build failures to Claude for deeper analysis.

### What it does

| Capability | Input | Output |
|-----------|-------|--------|
| **Failure analysis** | Last 2,000 lines of build log + build plan | Root cause (1-2 sentences), specific fix commands, prevention steps |
| **Optimization suggestions** | Build config + history summary | 3-5 actionable optimization recommendations |

### When it activates

- Only when `ANTHROPIC_API_KEY` is set as a secret
- Only on build failures (not on every build)
- Falls back silently to heuristic analysis when not configured

### Cost

Approximately $0.01-0.03 per failure analysis (Claude Sonnet, ~2K input tokens, ~300 output tokens).

---

## 14. CI Agent CLI — Complete Command Reference

The CI Agent is a standalone Python CLI tool that powers all the automation. It runs on any platform.

```bash
pip install ./agent
```

| Command | What it does | When it runs |
|---------|-------------|-------------|
| `ci-agent detect` | Scans repo, outputs BuildPlan (role, language, frameworks, etc.) | Start of every build |
| `ci-agent version` | Computes next version from conventional commits | Start of every build |
| `ci-agent version --apply` | Updates pyproject.toml with new version | After successful build on main |
| `ci-agent security` | Runs all available security tools, outputs unified report | Every build (parallel) |
| `ci-agent security --fail-on-high` | Same, but exits non-zero on critical/high findings | When gating is enabled |
| `ci-agent docker-gen` | Generates Dockerfile from golden template + repo config | Agent builds only |
| `ci-agent heal` | Reads build log, classifies failure, prescribes fix | On build failure |
| `ci-agent analyze` | Reads build history, generates insights + recommendations | On demand or scheduled |
| `ci-agent record` | Records a build result to history file | End of every build |

---

## 15. Repository Structure

```
scp-ci-templates/
│
├── .github/workflows/               CI/CD pipeline definitions
│   ├── ci-detect-and-build.yml      Main orchestrator (5 phases)
│   ├── ci-framework.yml             Framework: test → build → publish to CodeArtifact
│   ├── ci-agent-service.yml         Agent: test → docker-gen → docker build → push to ECR
│   ├── ci-security.yml              Security scanning (5 tools, parallel)
│   └── ci-agent-analyze.yml         Build analytics (scheduled)
│
├── agent/                            CI Agent Python package
│   ├── src/ci_agent/
│   │   ├── cli.py                   7 CLI commands
│   │   ├── models.py               Data models (BuildPlan, HealingAction, etc.)
│   │   ├── detect/                  Repo detection (6 modules)
│   │   ├── heal/                    Self-healing (3 modules, 10+ patterns)
│   │   ├── analyze/                 Build analytics (4 modules)
│   │   ├── version/                 Semantic versioning
│   │   ├── security/                Security scan orchestrator
│   │   ├── docker/                  Dockerfile generator
│   │   └── llm/                     Optional Claude integration
│   └── tests/                       52 unit tests
│
├── dockerfiles/
│   └── agent.Dockerfile             Golden Dockerfile template (centrally managed)
│
├── templates/                        Repo scaffolding templates
│   ├── framework/                   Library template
│   └── agent/                       Service template (no Dockerfile)
│
├── create-repo.sh                   CLI to scaffold new repos
├── docs/                            Documentation
├── examples/                        Example caller workflows
└── README.md
```

---

## 16. What Each Repo Needs

### Framework repo (minimum files)

```
my-framework/
├── .github/workflows/ci.yml         ← 15 lines, calls shared template
├── pyproject.toml                    ← package name, deps, version
├── src/my_framework/                 ← source code
└── tests/                            ← tests
```

### Agent repo (minimum files)

```
my-agent/
├── .github/workflows/ci.yml         ← 17 lines, calls shared template
├── pyproject.toml                    ← package name, deps, version
├── src/my_agent/
│   └── main.py                      ← FastAPI app
├── tests/                            ← tests
└── .ci-agent.yml                     ← (optional) Docker customization
```

No Dockerfile. No `.dockerignore`. No `requirements.txt`. No security tool config. No version management scripts. The platform handles all of it.

---

## 17. AWS Dependencies

| Service | Purpose | Used by |
|---------|---------|---------|
| **CodeArtifact** | Python package registry | Frameworks (publish) + Agents (pull during build) |
| **ECR** | Docker image registry | Agents (push) |
| **IAM** | Authentication via OIDC (no long-lived keys) | All builds |

### Required IAM permissions

**CodeArtifact:** `GetAuthorizationToken`, `GetRepositoryEndpoint`, `PublishPackageVersion`, `PutPackageMetadata`

**ECR:** `GetAuthorizationToken`, `BatchGetImage`, `BatchCheckLayerAvailability`, `CompleteLayerUpload`, `GetDownloadUrlForLayer`, `InitiateLayerUpload`, `PutImage`, `UploadLayerPart`

**STS:** `GetServiceBearerToken` (for CodeArtifact token exchange)

### Required secrets

| Secret | Where to set | Required? | Purpose |
|--------|-------------|-----------|---------|
| `AWS_ROLE_ARN` | GitHub org secrets | Yes | IAM role for CI to access CodeArtifact + ECR |
| `ANTHROPIC_API_KEY` | GitHub org secrets | No | Enables AI-powered failure analysis |

---

## 18. Licensing, Subscriptions & Credentials

### Software Licensing

Every tool used by this platform is free and open-source. No paid software licenses are required.

| Component | License | Cost |
|-----------|---------|------|
| Python | PSF (open source) | Free |
| uv | MIT / Apache 2.0 | Free |
| pytest | MIT | Free |
| pip-audit | Apache 2.0 | Free |
| bandit | Apache 2.0 | Free |
| trivy | Apache 2.0 | Free |
| hadolint | GPL-3.0 (standalone CLI usage — no linking concern) | Free |
| gitleaks | MIT | Free |
| Docker / Buildx | Apache 2.0 | Free |
| gh CLI | MIT | Free |

### Subscriptions Required

| Service | Type | What you need | Estimated cost |
|---------|------|--------------|----------------|
| **GitHub** | Org account (Free, Team, or Enterprise) | You already have `Aptos-Unified-Commerce` | Included in current plan |
| **AWS** | Pay-as-you-go account | Active account with billing enabled | See below |

**GitHub Actions minutes:**

| Plan | Included minutes/month | Overage |
|------|----------------------|---------|
| Free | 2,000 min | $0.008/min |
| Team | 3,000 min | $0.008/min |
| Enterprise | 50,000 min | $0.008/min |

Typical build: ~3–5 min. At 20 pushes/day across 10 repos → ~1,000–1,500 min/month (within free tier).

**AWS costs (usage-based, no license):**

| Service | Pricing | Typical cost |
|---------|---------|-------------|
| CodeArtifact | $0.05/GB stored + $0.09/GB transferred | < $5/month |
| ECR | $0.10/GB stored + data transfer | < $10/month |
| IAM / OIDC | Free | Free |

### Optional Subscription

| Service | Cost | Required? | What breaks without it |
|---------|------|-----------|----------------------|
| **Anthropic API** (Claude) | ~$0.01–0.03 per failure analysis | No | AI failure analysis disabled — everything else works |
| **Snyk** (future, not yet implemented) | Free tier: 200 tests/month; Paid: ~$25/dev/month | No | pip-audit + trivy continue to work as replacements |
| **Docker Hub** | Free: 100 pulls/6hrs per IP | No (rarely hits limit) | Mirror `python:3.11-slim` to ECR if rate-limited |

### Credentials to Configure

**One-time setup — GitHub org secrets** (`Settings → Secrets and variables → Actions`):

| Secret | Value | Required |
|--------|-------|----------|
| `AWS_ROLE_ARN` | `arn:aws:iam::123456789012:role/github-ci-role` | Yes |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | No |

**Per-repo values** (set in each repo's `ci.yml` or auto-filled by `create-repo.sh`):

| Input | Example | Required |
|-------|---------|----------|
| `codeartifact-domain` | `my-org` | Yes |
| `codeartifact-repo` | `python-packages` | Yes |
| `codeartifact-owner` | `123456789012` | Yes |
| `ecr-repository` | `scp-agent-orders` | Only for agents |
| `package-name` | `scp_ai_platform` | Yes |

### AWS Resources to Create (one-time setup)

| Resource | How to create | Notes |
|----------|-------------|-------|
| IAM OIDC Identity Provider | IAM Console → Identity Providers → Add `token.actions.githubusercontent.com` | Enables GitHub Actions to assume AWS roles without long-lived keys |
| IAM Role | IAM Console → Create role → Web identity → Trust GitHub OIDC | Attach CodeArtifact + ECR permissions (see Section 17) |
| CodeArtifact Domain | CodeArtifact Console → Create domain | One per org |
| CodeArtifact Repository | CodeArtifact Console → Create repository (under the domain) | One for all Python packages |
| ECR Repository | ECR Console → Create repository | One per agent service |

### What you do NOT need

- No Docker Hub paid account
- No PyPI account
- No Snyk account (yet)
- No SonarQube, Veracode, or any other paid SAST tool
- No Artifactory/Nexus license
- No Jenkins, CircleCI, or other CI platform subscription
- No code signing certificates
- No SSL certificates for CI

---

## 19. Summary

| Capability | How it works |
|-----------|-------------|
| **Detection** | CI Agent scans the repo → classifies as framework or agent → routes to correct pipeline |
| **Framework build** | `uv sync` → `pytest` → `uv build` → publish to CodeArtifact |
| **Agent build** | `uv sync` → `pytest` → generate Dockerfile from golden template → `docker build` → push to ECR |
| **Centralized Dockerfile** | Golden template in scp-ci-templates → generated at runtime → never in agent repos |
| **Self-healing** | 10+ failure patterns detected from logs → targeted fix applied → retry (up to 2x) |
| **Versioning** | Conventional commits → auto-bump pyproject.toml → git tag → always in sync |
| **Security** | 5 tools (pip-audit, bandit, trivy, hadolint, gitleaks) → unified report → optional deployment gate |
| **Analytics** | Build history tracked → failure trends, flaky tests, optimization suggestions |
| **AI analysis** | Optional Claude integration for root cause analysis on complex failures |
| **Repo scaffolding** | `create-repo.sh framework/agent` generates a ready-to-go repo with CI pre-configured |
| **Publishing** | Frameworks → CodeArtifact (Python packages), Agents → ECR (Docker images) |
