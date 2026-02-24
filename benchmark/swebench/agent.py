"""Plankton SWE-bench agent wrapper — HAL-compatible solve() + CLI entry point."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

GIT = shutil.which("git") or "git"
CLAUDE = shutil.which("claude") or "claude"
BARE_SETTINGS = Path.home() / ".claude" / "bare-settings.json"


def _write_prompt_file(prompt: str, work_dir: Path) -> Path:
    """Write prompt to work_dir/.swebench_prompt.txt, return path."""
    p = work_dir / ".swebench_prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    return p


def _extract_patch(repo_dir: Path, original_sha: str | None = None) -> str:
    """Run git diff against original_sha (or HEAD if not provided), return stdout."""
    diff_target = original_sha or "HEAD"
    result = subprocess.run(
        [GIT, "diff", diff_target],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def _parse_claude_output(result: subprocess.CompletedProcess, elapsed: float) -> dict:
    """Parse JSON stdout. Fallback to raw_stdout on invalid JSON."""
    metadata: dict = {"returncode": result.returncode, "elapsed_s": round(elapsed, 1)}
    try:
        metadata["claude_output"] = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        metadata["raw_stdout"] = result.stdout[:2000]
    if "claude_output" in metadata:
        parsed = metadata["claude_output"]
        cost = parsed.get("cost_usd")
        if cost is None:
            cost = (parsed.get("usage") or {}).get("cost_usd")
        if cost is not None:
            metadata["cost_usd"] = cost
    if result.returncode not in {0, None} and "claude_output" not in metadata:
        metadata["error_type"] = "infra"
    if result.stderr:
        metadata["stderr"] = result.stderr[:2000]
    return metadata


def _build_cmd(condition: str, model: str, prompt_file: Path) -> list[str]:
    """Build the full command for subprocess.run.

    Shape: ["script", "-q", "/dev/null", "sh", "-c", "cat {prompt_file} | {claude_cmd}"]
    """
    claude_args = [
        CLAUDE,
        "-p",
        "--dangerously-skip-permissions",
        "--disallowedTools",
        "WebFetch,WebSearch,Task",
        "--output-format",
        "json",
        "--model",
        model,
    ]

    if condition == "baseline":
        claude_args[1:1] = [
            "--setting-sources",
            "",
            "--settings",
            str(BARE_SETTINGS),
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]

    claude_cmd = " ".join(str(a) for a in claude_args)
    shell_cmd = f"cat {shlex.quote(str(prompt_file))} | {claude_cmd}"
    return ["script", "-q", "/dev/null", "sh", "-c", shell_cmd]


_VALID_CONDITIONS = {"baseline", "plankton"}


_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def solve(
    input_data: dict,
    *,
    condition: str = "plankton",
    model: str | None = None,
    timeout: int = 1800,
    **_kwargs,
) -> dict:
    """HAL-compatible solve function.

    input_data has: instance_id, problem_statement, repo_dir
    Returns: {"patch": str, "condition": str, "passed": None, "metadata": dict}

    ``passed`` is always None here — it is populated by the evaluation harness
    after the benchmark run completes.
    """
    if condition not in _VALID_CONDITIONS:
        msg = f"invalid condition: {condition!r}, must be one of {_VALID_CONDITIONS}"
        raise ValueError(msg)

    resolved_model = model or os.environ.get("SWEBENCH_MODEL") or _DEFAULT_MODEL

    repo_dir = Path(input_data["repo_dir"])

    # Capture original HEAD so _extract_patch diffs against it even if claude commits
    sha_result = subprocess.run(
        [GIT, "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    original_sha = sha_result.stdout.strip() or None

    prompt_file = _write_prompt_file(input_data["problem_statement"], repo_dir)
    cmd = _build_cmd(condition, resolved_model, prompt_file)

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        elapsed = time.time() - start
        metadata = _parse_claude_output(result, elapsed)
        patch = _extract_patch(repo_dir, original_sha)
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        metadata = {"error": "timeout", "error_type": "infra", "elapsed_s": round(elapsed, 1)}
        patch = ""

    return {"patch": patch, "condition": condition, "passed": None, "metadata": metadata}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SWE-bench agent runner")
    parser.add_argument("--condition", default="plankton", choices=sorted(_VALID_CONDITIONS))
    parser.add_argument("--repo-dir", required=True, help="Path to the repo checkout")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Inline prompt text")
    prompt_group.add_argument("--prompt-file", help="Path to prompt file")
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID (default: $SWEBENCH_MODEL or claude-haiku-4-5-20251001)",
    )
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print command without executing")
    return parser


def main() -> None:
    """CLI entry point."""
    args = _build_parser().parse_args()

    repo_dir = Path(args.repo_dir)

    prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt

    if args.dry_run:
        prompt_file = _write_prompt_file(prompt, repo_dir)
        cmd = _build_cmd(args.condition, args.model, prompt_file)
        print(f"[DRY RUN] {' '.join(str(c) for c in cmd)}")
        print(f"[DRY RUN] cwd: {repo_dir}")
        return

    result = solve(
        {"instance_id": "cli", "problem_statement": prompt, "repo_dir": str(repo_dir)},
        condition=args.condition,
        model=args.model,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
