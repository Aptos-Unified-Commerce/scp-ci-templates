"""Agentic LLM-powered analysis using Claude API with tool use.

Instead of just dumping logs to Claude, this module gives Claude tools
to investigate failures: read files, check git blame, query build history,
and search for similar failures. Claude reasons through the investigation
in multiple steps.

Only activates when ANTHROPIC_API_KEY is set. Falls back gracefully otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def is_available() -> bool:
    """Check if LLM analysis is available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# --- Tools that Claude can use during investigation ---

INVESTIGATION_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file from the repository. Use this to inspect source code, config files, or test files that may be related to the failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file from repo root"},
                "start_line": {"type": "integer", "description": "Start reading from this line (1-based, optional)"},
                "end_line": {"type": "integer", "description": "Stop reading at this line (optional)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "git_blame",
        "description": "Run git blame on a specific file and line range to find who last changed it and when. Use this to identify recent changes that may have caused the failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "start_line": {"type": "integer", "description": "Start line for blame"},
                "end_line": {"type": "integer", "description": "End line for blame"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "git_log_recent",
        "description": "Get recent git commit messages and changed files. Use this to see what changed recently that may have introduced the failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of recent commits to show (default 10)"},
            },
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across all source files in the repo. Use this to find related code, imports, or usages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "file_glob": {"type": "string", "description": "File glob pattern to limit search (e.g., '*.py', 'src/**/*.py')"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "query_build_history",
        "description": "Query the build history for this repo. Use this to check if this failure has happened before, what strategies were tried, and whether builds were healthy recently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["recent_failures", "healing_stats", "build_trend", "all_recent"],
                    "description": "What to query: recent_failures, healing_stats, build_trend, or all_recent",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory. Use this to understand the project structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Relative path to directory (default: repo root)"},
            },
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, repo_path: str, build_records: list | None) -> str:
    """Execute a tool call and return the result as a string."""
    path = Path(repo_path)

    try:
        if tool_name == "read_file":
            file_path = path / tool_input["path"]
            if not file_path.exists():
                return f"File not found: {tool_input['path']}"
            lines = file_path.read_text(errors="ignore").splitlines()
            start = tool_input.get("start_line", 1) - 1
            end = tool_input.get("end_line", len(lines))
            selected = lines[max(0, start):min(end, len(lines))]
            return "\n".join(f"{i + start + 1}: {line}" for i, line in enumerate(selected))

        elif tool_name == "git_blame":
            cmd = ["git", "blame", tool_input["path"]]
            if "start_line" in tool_input and "end_line" in tool_input:
                cmd.extend(["-L", f"{tool_input['start_line']},{tool_input['end_line']}"])
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=path, timeout=15)
            return result.stdout[:3000] if result.returncode == 0 else f"git blame failed: {result.stderr}"

        elif tool_name == "git_log_recent":
            n = tool_input.get("n", 10)
            result = subprocess.run(
                ["git", "log", f"-{n}", "--pretty=format:%h %s (%an, %ar)", "--stat", "--stat-width=80"],
                capture_output=True, text=True, cwd=path, timeout=15,
            )
            return result.stdout[:5000] if result.returncode == 0 else "git log failed"

        elif tool_name == "search_code":
            cmd = ["grep", "-rn", "--include", tool_input.get("file_glob", "*"), tool_input["pattern"], "."]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=path, timeout=15)
            output = result.stdout[:3000]
            return output if output else "No matches found"

        elif tool_name == "query_build_history":
            if not build_records:
                return "No build history available"
            query = tool_input["query"]
            if query == "recent_failures":
                failures = [r for r in build_records if r.get("status") == "failure"][-10:]
                return json.dumps(failures, indent=2) if failures else "No recent failures"
            elif query == "healing_stats":
                healed = [r for r in build_records if r.get("healing_strategy")]
                return json.dumps(healed[-10:], indent=2) if healed else "No healing history"
            elif query == "build_trend":
                recent = build_records[-20:]
                return json.dumps([{"status": r.get("status"), "duration": r.get("duration_seconds")} for r in recent], indent=2)
            else:
                return json.dumps(build_records[-10:], indent=2)

        elif tool_name == "list_files":
            dir_path = path / tool_input.get("directory", ".")
            if not dir_path.is_dir():
                return f"Directory not found: {tool_input.get('directory', '.')}"
            entries = sorted(str(p.relative_to(path)) for p in dir_path.iterdir() if not p.name.startswith("."))
            return "\n".join(entries[:100])

        return f"Unknown tool: {tool_name}"

    except subprocess.TimeoutExpired:
        return f"Tool timed out: {tool_name}"
    except Exception as e:
        return f"Tool error: {e}"


def investigate_failure(
    log_content: str,
    repo_path: str = ".",
    build_plan: dict | None = None,
    build_records: list[dict] | None = None,
    max_turns: int = 5,
) -> str | None:
    """Run an agentic investigation of a build failure.

    Claude gets tools to read files, check git blame, query history,
    and search code. It investigates in multiple steps before producing
    a final analysis.

    Args:
        log_content: The build log output.
        repo_path: Path to the repository root.
        build_plan: Detection output (BuildPlan dict).
        build_records: Recent build history records (list of dicts).
        max_turns: Maximum tool-use turns (prevents runaway).

    Returns:
        Markdown analysis or None if LLM unavailable.
    """
    if not is_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()

    # Truncate log to last 1500 lines
    lines = log_content.splitlines()
    truncated_log = "\n".join(lines[-1500:]) if len(lines) > 1500 else log_content

    system_prompt = """You are a senior DevOps engineer investigating a CI/CD build failure.
You have tools to read source files, check git blame, view recent commits, search code, and query build history.

Your investigation process:
1. Read the build log carefully — identify the exact error
2. Use tools to investigate: check the failing file, recent changes, related code
3. Check build history to see if this is a recurring issue
4. Produce a concise analysis with root cause, fix, and prevention

Be precise and specific. Reference exact file paths and line numbers.
Keep your final analysis under 400 words."""

    context_parts = [f"## Build Log (last {min(len(lines), 1500)} lines)\n```\n{truncated_log}\n```"]
    if build_plan:
        context_parts.append(f"## Build Plan\n```json\n{json.dumps(build_plan, indent=2)}\n```")

    messages = [{"role": "user", "content": "\n\n".join(context_parts)}]

    # Agentic loop — let Claude use tools to investigate
    for turn in range(max_turns):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            tools=INVESTIGATION_TOOLS,
            messages=messages,
        )

        # Check if Claude wants to use a tool
        if response.stop_reason == "tool_use":
            # Process all tool calls in this response
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(
                        block.name, block.input, repo_path, build_records
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            # Claude is done investigating — extract the final text
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            break
        else:
            break

    return None


def suggest_optimizations(
    build_plan: dict,
    history_summary: str,
) -> str | None:
    """Ask Claude for build pipeline optimization suggestions."""
    if not is_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()

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
