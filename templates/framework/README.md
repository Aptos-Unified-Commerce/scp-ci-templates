# {{project_name}}

{{description}}

## Local Development

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Build package
uv build
```

## CI/CD

This repo uses [scp-ci-templates](https://github.com/Aptos-Unified-Commerce/scp-ci-templates) for CI/CD.

On every push/PR:
- Auto-detection, build, test, security scanning
- Self-healing on transient failures

On push to `main`:
- Publishes to AWS CodeArtifact
- Auto-versions from conventional commits (`feat:` → minor, `fix:` → patch)
- Creates git tag `v{version}`

### Conventional Commits

```bash
git commit -m "feat: add new feature"      # minor bump
git commit -m "fix: handle edge case"      # patch bump
git commit -m "feat!: breaking change"     # major bump
```
