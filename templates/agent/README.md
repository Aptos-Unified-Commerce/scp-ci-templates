# {{project_name}}

{{description}}

## Local Development

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run locally
uv run uvicorn {{package_name}}.main:app --reload
```

## Docker

```bash
# Build
docker build -t {{project_name}} .

# Run
docker run -p 8000:8000 {{project_name}}
```

## CI/CD

This repo uses [scp-ci-templates](https://github.com/Aptos-Unified-Commerce/scp-ci-templates) for CI/CD.

On every push/PR:
- Auto-detection, test, Docker build, security scanning
- Self-healing on transient failures

On push to `main`:
- Builds Docker image and pushes to AWS ECR
- Auto-versions from conventional commits
- Creates git tag `v{version}`

### Conventional Commits

```bash
git commit -m "feat: add new endpoint"     # minor bump
git commit -m "fix: handle timeout"        # patch bump
git commit -m "feat!: remove old API"      # major bump
```
