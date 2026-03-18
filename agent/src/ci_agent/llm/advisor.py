"""Optional LLM-powered analysis using Claude API.

Only activates when ANTHROPIC_API_KEY is set. Falls back gracefully otherwise.
"""

from __future__ import annotations

import os


def is_available() -> bool:
    """Check if LLM analysis is available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def analyze_failure(
    log_content: str,
    build_plan: dict | None = None,
    history_summary: str | None = None,
) -> str | None:
    """Send failure context to Claude for root cause analysis.

    Returns a markdown analysis or None if LLM is unavailable.
    """
    if not is_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()

    # Truncate log to last 2000 lines to stay within token budget
    lines = log_content.splitlines()
    truncated_log = "\n".join(lines[-2000:]) if len(lines) > 2000 else log_content

    context_parts = [f"## Build Log (last {min(len(lines), 2000)} lines)\n```\n{truncated_log}\n```"]

    if build_plan:
        import json

        context_parts.append(f"## Build Plan\n```json\n{json.dumps(build_plan, indent=2)}\n```")

    if history_summary:
        context_parts.append(f"## Recent Build History\n{history_summary}")

    context = "\n\n".join(context_parts)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are a CI/CD expert analyzing a build failure. Provide a concise analysis with:

1. **Root Cause**: What exactly failed and why (1-2 sentences)
2. **Fix**: The specific commands or code changes needed (be precise)
3. **Prevention**: How to prevent this from happening again

Keep your response under 300 words. Be specific, not generic.

{context}""",
            }
        ],
    )

    return message.content[0].text


def suggest_optimizations(
    build_plan: dict,
    history_summary: str,
) -> str | None:
    """Ask Claude for build pipeline optimization suggestions.

    Returns markdown suggestions or None if LLM is unavailable.
    """
    if not is_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()

    import json

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are a CI/CD optimization expert. Based on this build configuration and history, suggest specific, actionable optimizations.

Focus on:
- Build speed improvements
- Caching strategies
- Parallelization opportunities
- Resource usage optimization

Keep each suggestion to 1-2 sentences with concrete actions. Return 3-5 suggestions max.

## Build Configuration
```json
{json.dumps(build_plan, indent=2)}
```

## Build History Summary
{history_summary}""",
            }
        ],
    )

    return message.content[0].text
