# SCP CI Templates

Reusable GitHub Actions workflows for SCP services. Provides a single entry point that auto-detects the build type:

- **No Dockerfile** → Python library build with uv → publish to **AWS CodeArtifact**
- **Dockerfile found** → Docker image build → push to **AWS ECR**

---

## Repository Structure

```
scp-ci-templates/
├── .github/workflows/
│   ├── ci-detect-and-build.yml   # Smart router: detects Dockerfile, picks the right path
│   ├── ci-python.yml             # Reusable: uv build + test + publish to CodeArtifact
│   └── ci-docker.yml             # Reusable: Docker build + push to ECR
├── examples/
│   ├── caller-library.yml        # Example: how a Python library repo calls the template
│   └── caller-service.yml        # Example: how a Dockerized service repo calls the template
└── README.md
```

---

## How It Works

```
Caller repo CI
      │
      ▼
ci-detect-and-build.yml
      │
      ├── Dockerfile found?
      │       │
      │       YES → ci-docker.yml → Build image → Push to ECR
      │       │
      │       NO  → ci-python.yml → uv build + test → Publish to CodeArtifact
      │
      ▼
   Done
```

---

## Available Workflows

### 1. `ci-detect-and-build.yml` — Smart Router (Recommended)

Auto-detects whether the repo has a Dockerfile and routes to the appropriate build workflow. **Use this as your single entry point.**

#### Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `python-version` | No | `3.11` | Python version |
| `aws-region` | No | `us-east-1` | AWS region |
| `package-name` | Yes | — | Python package name (for artifact upload) |
| `codeartifact-domain` | Yes | — | CodeArtifact domain |
| `codeartifact-repo` | Yes | — | CodeArtifact repository |
| `codeartifact-owner` | Yes | — | AWS account ID |
| `ecr-repository` | No | `""` | ECR repo name (required if repo has Dockerfile) |
| `dockerfile-path` | No | `Dockerfile` | Path to Dockerfile |
| `docker-context` | No | `.` | Docker build context |

#### Secrets

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | IAM role ARN with CodeArtifact and/or ECR permissions |

---

### 2. `ci-python.yml` — Python Library Build

Use directly if you know the repo is always a Python library.

- Installs dependencies with `uv sync --all-extras`
- Runs `uv run pytest`
- Builds with `uv build`
- Publishes to CodeArtifact when `publish: true`

---

### 3. `ci-docker.yml` — Docker Build & Push

Use directly if you know the repo always has a Dockerfile.

- Optionally runs `uv run pytest` before Docker build
- Builds Docker image with Buildx (layer caching enabled)
- Pushes to ECR with tags: `<sha>`, `<branch>`, `latest` (on main)

---

## Usage — Calling from Your Repo

### Option A: Smart detection (recommended)

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
```

That's it. The template handles everything:
- If your repo has a `Dockerfile` → builds and pushes to ECR
- If not → builds Python package and publishes to CodeArtifact

### Option B: Python library only

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    uses: Aptos-Unified-Commerce/scp-ci-templates/.github/workflows/ci-python.yml@main
    with:
      package-name: scp_ai_platform
      codeartifact-domain: my-domain
      codeartifact-repo: my-repo
      codeartifact-owner: "123456789012"
      publish: ${{ github.ref == 'refs/heads/main' && github.event_name == 'push' }}
    secrets:
      AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
```

### Option C: Docker service only

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    uses: Aptos-Unified-Commerce/scp-ci-templates/.github/workflows/ci-docker.yml@main
    with:
      ecr-repository: my-service
    secrets:
      AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
```

---

## Updating scp-ai-platform to Use Templates

Replace the existing `.github/workflows/ci.yml` in `scp-ai-platform` with:

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
      package-name: scp_ai_platform
      codeartifact-domain: your-domain         # ← change
      codeartifact-repo: your-repo             # ← change
      codeartifact-owner: "123456789012"       # ← change
    secrets:
      AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
```

---

## AWS Prerequisites

### IAM Role Permissions

The IAM role needs permissions for both CodeArtifact and ECR:

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

The IAM role must trust GitHub Actions:

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

---

## GitHub Secret

Each caller repo needs one secret:

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | `arn:aws:iam::<ACCOUNT_ID>:role/<ROLE_NAME>` |

This can be set at the **organization level** so all repos inherit it automatically.
