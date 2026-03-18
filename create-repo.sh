#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# SCP Repo Scaffolder
#
# Creates a new framework or agent repo from templates.
#
# Usage:
#   ./create-repo.sh framework my-library "My shared library"
#   ./create-repo.sh agent my-service "My agent service"
#
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="${SCRIPT_DIR}/templates"

# --- Defaults (override via env vars) ---
CODEARTIFACT_DOMAIN="${CODEARTIFACT_DOMAIN:-your-domain}"
CODEARTIFACT_REPO="${CODEARTIFACT_REPO:-your-repo}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-123456789012}"
GITHUB_ORG="${GITHUB_ORG:-Aptos-Unified-Commerce}"
OUTPUT_DIR="${OUTPUT_DIR:-.}"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    echo -e "${BOLD}SCP Repo Scaffolder${NC}"
    echo ""
    echo -e "Usage: ${GREEN}./create-repo.sh <template> <project-name> <description>${NC}"
    echo ""
    echo "Templates:"
    echo "  framework   Python library → published to CodeArtifact"
    echo "  agent       Python service with Dockerfile → pushed to ECR"
    echo ""
    echo "Examples:"
    echo "  ./create-repo.sh framework scp-auth-lib \"Shared authentication library\""
    echo "  ./create-repo.sh agent scp-agent-orders \"Order processing agent service\""
    echo ""
    echo "Environment variables (optional):"
    echo "  CODEARTIFACT_DOMAIN   CodeArtifact domain (default: your-domain)"
    echo "  CODEARTIFACT_REPO     CodeArtifact repo   (default: your-repo)"
    echo "  AWS_ACCOUNT_ID        AWS account ID       (default: 123456789012)"
    echo "  GITHUB_ORG            GitHub org            (default: Aptos-Unified-Commerce)"
    echo "  OUTPUT_DIR            Where to create repo  (default: current dir)"
    exit 1
}

# --- Validate args ---
if [ $# -lt 3 ]; then
    usage
fi

TEMPLATE="$1"
PROJECT_NAME="$2"
DESCRIPTION="$3"

if [ "$TEMPLATE" != "framework" ] && [ "$TEMPLATE" != "agent" ]; then
    echo -e "${RED}Error: Template must be 'framework' or 'agent'${NC}"
    usage
fi

TEMPLATE_DIR="${TEMPLATES_DIR}/${TEMPLATE}"
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo -e "${RED}Error: Template directory not found: ${TEMPLATE_DIR}${NC}"
    exit 1
fi

# --- Derive names ---
# project-name → package_name (replace hyphens with underscores)
PACKAGE_NAME=$(echo "$PROJECT_NAME" | tr '-' '_')
ECR_REPOSITORY="$PROJECT_NAME"
REPO_DIR="${OUTPUT_DIR}/${PROJECT_NAME}"

# --- Check target doesn't exist ---
if [ -d "$REPO_DIR" ]; then
    echo -e "${RED}Error: Directory already exists: ${REPO_DIR}${NC}"
    exit 1
fi

echo -e "${BLUE}${BOLD}Creating ${TEMPLATE} repo: ${PROJECT_NAME}${NC}"
echo "  Package name:  ${PACKAGE_NAME}"
echo "  Description:   ${DESCRIPTION}"
echo "  Directory:     ${REPO_DIR}"
echo ""

# --- Copy template ---
mkdir -p "$REPO_DIR"

# Copy all files including hidden ones, but skip {{package_name}} dirs (handled separately)
find "$TEMPLATE_DIR" -type f | while read -r src; do
    # Get relative path from template dir
    rel="${src#$TEMPLATE_DIR/}"

    # Replace {{package_name}} in path
    dst_rel=$(echo "$rel" | sed "s/{{package_name}}/${PACKAGE_NAME}/g")
    dst="${REPO_DIR}/${dst_rel}"

    # Create parent directory
    mkdir -p "$(dirname "$dst")"

    # Copy and replace all placeholders
    sed \
        -e "s/{{project_name}}/${PROJECT_NAME}/g" \
        -e "s/{{package_name}}/${PACKAGE_NAME}/g" \
        -e "s/{{description}}/${DESCRIPTION}/g" \
        -e "s/{{codeartifact_domain}}/${CODEARTIFACT_DOMAIN}/g" \
        -e "s/{{codeartifact_repo}}/${CODEARTIFACT_REPO}/g" \
        -e "s/{{aws_account_id}}/${AWS_ACCOUNT_ID}/g" \
        -e "s/{{ecr_repository}}/${ECR_REPOSITORY}/g" \
        "$src" > "$dst"
done

echo -e "${GREEN}Files created.${NC}"

# --- Init git ---
cd "$REPO_DIR"
git init -b main > /dev/null 2>&1
git add -A
git commit -m "Initial commit — scaffolded from scp-ci-templates/${TEMPLATE} template" > /dev/null 2>&1

echo -e "${GREEN}Git initialized.${NC}"

# --- Create GitHub repo (optional) ---
if command -v gh &> /dev/null; then
    echo ""
    read -p "Create GitHub repo at ${GITHUB_ORG}/${PROJECT_NAME}? (y/N) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gh repo create "${GITHUB_ORG}/${PROJECT_NAME}" \
            --private \
            --description "${DESCRIPTION}" \
            --source . \
            --push
        echo -e "${GREEN}Repo created: https://github.com/${GITHUB_ORG}/${PROJECT_NAME}${NC}"
    fi
fi

# --- Done ---
echo ""
echo -e "${GREEN}${BOLD}Done!${NC} Your ${TEMPLATE} repo is ready at: ${REPO_DIR}"
echo ""
echo "Next steps:"
echo "  cd ${REPO_DIR}"
if [ "$TEMPLATE" = "framework" ]; then
    echo "  uv sync --all-extras    # Install dependencies"
    echo "  uv run pytest           # Run tests"
    echo "  uv build                # Build package"
else
    echo "  uv sync --all-extras    # Install dependencies"
    echo "  uv run pytest           # Run tests"
    echo "  docker build -t ${PROJECT_NAME} .   # Build image"
fi
