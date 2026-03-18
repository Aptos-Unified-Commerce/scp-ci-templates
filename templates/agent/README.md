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

## CI/CD

This repo uses [scp-ci-templates](https://github.com/Aptos-Unified-Commerce/scp-ci-templates) for CI/CD.

The Dockerfile is **centrally managed** — it is generated at build time from the golden template
in scp-ci-templates. To customize Docker behavior, edit `.ci-agent.yml`:

```yaml
docker:
  python_version: "3.11"    # Base image Python version
  port: 8000                # Exposed port
  entrypoint: '["uvicorn", "{{package_name}}.main:app", "--host", "0.0.0.0", "--port", "8000"]'
  extra_system_packages: [] # Runtime apt packages (e.g., ["libpq5"])
  extra_build_packages: []  # Build-time apt packages (e.g., ["gcc", "libpq-dev"])
```

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
