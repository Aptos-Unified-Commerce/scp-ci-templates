# ============================================================================
# SCP Agent Service — Golden Dockerfile
#
# MANAGED BY: scp-ci-templates (DO NOT copy into agent repos)
# This Dockerfile is injected at CI runtime. To update the base image,
# Python version, or security hardening for ALL agents, edit this file.
#
# Customizable per-repo via .ci-agent.yml:
#   entrypoint, port, extra_system_packages
# ============================================================================

# --- Stage 1: Build dependencies ---
FROM python:{{python_version}}-slim AS builder

ARG PIP_EXTRA_INDEX_URL

WORKDIR /build

# Install system packages needed for building (if any)
{{extra_build_packages}}

# Install Python dependencies
COPY requirements.txt* pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt 2>/dev/null \
    || pip install --no-cache-dir --prefix=/install . 2>/dev/null \
    || true

# --- Stage 2: Runtime image ---
FROM python:{{python_version}}-slim

LABEL maintainer="Aptos Unified Commerce Platform"
LABEL managed-by="scp-ci-templates"

ARG PIP_EXTRA_INDEX_URL

WORKDIR /app

# Install runtime system packages (if any)
{{extra_runtime_packages}}

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ ./src/
COPY pyproject.toml ./

# Install the project itself (editable-like, so entry points work)
RUN pip install --no-cache-dir --no-deps . 2>/dev/null || true

EXPOSE {{port}}

# Security: run as non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --create-home appuser

# Security: remove setuid/setgid binaries to reduce attack surface
RUN find / -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# Security: make system dirs read-only where possible
RUN chmod a-w /etc/passwd /etc/group 2>/dev/null || true

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{{port}}/health')" || exit 1

# Labels for runtime security policies (consumed by orchestrators)
LABEL security.read-only-root="recommended"
LABEL security.no-new-privileges="true"
LABEL security.drop-capabilities="ALL"

CMD {{entrypoint}}
