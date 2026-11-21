"""Fail-closed planner and aggregator for Security and regression CI."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ZERO_SHA = "0" * 40
LIGHTWEIGHT_DRAFT_EXACT = frozenset({"AGENTS.md", "MIGRATION_STATUS.md"})
LIGHTWEIGHT_DRAFT_REGEXES = (
    re.compile(
        r"^tools/(?:evaluate_rl|rl|benchmark_rl|diagnose_rl|run_rl)_[A-Za-z0-9_]+\.(?:py|cjs)$"
    ),
    re.compile(r"^tests/test_rl_[A-Za-z0-9_]+\.(?:py|js|cjs)$"),
)


def is_lightweight_draft_path(path: str) -> bool:
    """Return True only for isolated RL research scripts, RL tests, or workflow notes."""
    if path in LIGHTWEIGHT_DRAFT_EXACT:
        return True
    return any(pattern.fullmatch(path) is not None for pattern in LIGHTWEIGHT_DRAFT_REGEXES)


def select_diff_range(
    *,
    event_action: str,
    base_sha: str,
    head_sha: str,
    before_sha: str,
    after_sha: str,
) -> tuple[str, str]:
    """Use incremental commit range on Draft synchronize, full PR range otherwise."""
    if (
        event_action == "synchronize"
        and before_sha
        and after_sha
        and before_sha != ZERO_SHA
        and after_sha != ZERO_SHA
    ):
        return before_sha, after_sha
    return base_sha, head_sha


def decide_run_heavy(
    *,
    event_name: str,
    is_draft: bool,
    changed_files: list[str] | None,
) -> tuple[bool, str]:
    """Require heavy container/browser/SBOM checks unless a Draft PR touches only RL paths."""
    if event_name != "pull_request":
        return True, f"event_name={event_name} requires full suite"
    if not is_draft:
        return True, "non-draft pull request requires full suite"
    if not changed_files:
        return True, "empty or unavailable diff fails closed to full suite"
    non_lightweight = [path for path in changed_files if not is_lightweight_draft_path(path)]
    if non_lightweight:
        return True, f"non-RL paths touched ({non_lightweight[0]})"
    return False, f"draft PR touches only {len(changed_files)} RL/doc file(s)"


def git_changed_files(left_sha: str, right_sha: str) -> list[str] | None:
    """Resolve three-dot diff; return None on missing refs or command failure."""
    if not left_sha or not right_sha:
        return None
    for sha in (left_sha, right_sha):
        check = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True, text=True,
        )
        if check.returncode != 0:
            subprocess.run(
                ["git", "fetch", "--no-tags", "--depth=1", "origin", sha],
                capture_output=True, text=True,
            )
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{left_sha}...{right_sha}"],
        capture_output=True, text=True,
    )
    if diff.returncode != 0:
        return None
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def verify_aggregate(
    *,
    run_heavy: bool,
    plan_result: str,
    regression_result: str,
    container_result: str,
    browser_result: str,
) -> tuple[bool, str]:
    """Validate fan-in job results so skipped heavy checks pass only when run_heavy is false."""
    if plan_result != "success":
        return False, f"plan job did not succeed: {plan_result}"
    if regression_result != "success":
        return False, f"regression-tests job did not succeed: {regression_result}"
    allowed_heavy = {"success"} if run_heavy else {"skipped"}
    if container_result not in allowed_heavy:
        return False, f"container-and-audit unexpected result={container_result} (run_heavy={run_heavy})"
    if browser_result not in allowed_heavy:
        return False, f"browser-csp unexpected result={browser_result} (run_heavy={run_heavy})"
    return True, f"all required gates satisfied (run_heavy={run_heavy})"


def _parse_bool(value: str) -> bool:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    raise argparse.ArgumentTypeError(f"Expected 'true' or 'false', got {value!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--event-name", required=True)
    plan_cmd.add_argument("--event-action", default="")
    plan_cmd.add_argument("--is-draft", type=_parse_bool, required=True)
    plan_cmd.add_argument("--base-sha", default="")
    plan_cmd.add_argument("--head-sha", default="")
    plan_cmd.add_argument("--before-sha", default="")
    plan_cmd.add_argument("--after-sha", default="")

    agg_cmd = sub.add_parser("verify")
    agg_cmd.add_argument("--run-heavy", type=_parse_bool, required=True)
    agg_cmd.add_argument("--plan-result", required=True)
    agg_cmd.add_argument("--regression-result", required=True)
    agg_cmd.add_argument("--container-result", required=True)
    agg_cmd.add_argument("--browser-result", required=True)

    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.event_name == "pull_request" and args.is_draft:
            left_sha, right_sha = select_diff_range(
                event_action=args.event_action,
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                before_sha=args.before_sha,
                after_sha=args.after_sha,
            )
            changed = git_changed_files(left_sha, right_sha)
        else:
            changed = None
        run_heavy, reason = decide_run_heavy(
            event_name=args.event_name,
            is_draft=args.is_draft,
            changed_files=changed,
        )
        value = "true" if run_heavy else "false"
        print(f"run_heavy={value} ({reason})")
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as fh:
                fh.write(f"run_heavy={value}\n")
        return 0

    ok, message = verify_aggregate(
        run_heavy=args.run_heavy,
        plan_result=args.plan_result,
        regression_result=args.regression_result,
        container_result=args.container_result,
        browser_result=args.browser_result,
    )
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
