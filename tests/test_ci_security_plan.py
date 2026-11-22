"""Tests for fail-closed CI heavy-gate planner and aggregator."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.ci_security_plan import (
    ZERO_SHA,
    decide_run_heavy,
    git_changed_files,
    is_lightweight_draft_path,
    main,
    select_diff_range,
    verify_aggregate,
)

ROOT = Path(__file__).resolve().parent.parent


class CiSecurityPlanTests(unittest.TestCase):
    def test_allowlist_permits_only_isolated_rl_and_note_files(self):
        self.assertTrue(is_lightweight_draft_path("AGENTS.md"))
        self.assertTrue(is_lightweight_draft_path("MIGRATION_STATUS.md"))
        self.assertTrue(is_lightweight_draft_path("tools/evaluate_rl_azumarill_switch_clock.py"))
        self.assertTrue(is_lightweight_draft_path("tools/rl_azumarill_switch_rl_worker.cjs"))
        self.assertTrue(is_lightweight_draft_path("tools/run_rl_mc.py"))
        self.assertTrue(is_lightweight_draft_path("tests/test_rl_azumarill_switch_150s.py"))
        self.assertTrue(is_lightweight_draft_path("tests/test_rl_charge_branches.cjs"))

        # Container-copied, workflow, or runtime files must fail closed to full suite.
        for sensitive in (
            "Dockerfile",
            "requirements.lock",
            "start.sh",
            "pvpoke_web.py",
            "pvpoke_rl_team_native.js",
            "tools/cloud_migration_backup.py",
            "tools/ci_security_plan.py",
            "tests/smoke_minior_direct.py",
            "tests/stage7_container_smoke.py",
            "tests/test_proxy_gateway.py",
            "tests/test_real_enospc.py",
            "tests/security_browser.cjs",
            "tests/test_ci_security_plan.py",
            ".github/workflows/security-regression.yml",
            "tools/nested/rl_helper.py",
        ):
            self.assertFalse(is_lightweight_draft_path(sensitive), sensitive)

    def test_decide_run_heavy_fails_closed(self):
        # Non-PR and ready-for-review PR always run heavy checks.
        self.assertTrue(decide_run_heavy(
            event_name="push", is_draft=False, changed_files=["AGENTS.md"],
        )[0])
        self.assertTrue(decide_run_heavy(
            event_name="workflow_dispatch", is_draft=False, changed_files=["AGENTS.md"],
        )[0])
        self.assertTrue(decide_run_heavy(
            event_name="pull_request", is_draft=False,
            changed_files=["tools/evaluate_rl_azumarill_switch_clock.py"],
        )[0])

        # Missing or empty diff in draft fails closed.
        self.assertTrue(decide_run_heavy(
            event_name="pull_request", is_draft=True, changed_files=None,
        )[0])
        self.assertTrue(decide_run_heavy(
            event_name="pull_request", is_draft=True, changed_files=[],
        )[0])

        # Mixed RL + runtime/container file fails closed.
        self.assertTrue(decide_run_heavy(
            event_name="pull_request", is_draft=True,
            changed_files=["tools/evaluate_rl_azumarill_switch_150s.py", "tools/cloud_migration_backup.py"],
        )[0])

        # Pure RL draft change skips heavy container/browser jobs.
        heavy, _ = decide_run_heavy(
            event_name="pull_request", is_draft=True,
            changed_files=[
                "AGENTS.md",
                "tools/evaluate_rl_azumarill_switch_rl_150s.py",
                "tools/rl_azumarill_switch_rl_worker.cjs",
                "tests/test_rl_azumarill_switch_rl_150s.py",
            ],
        )
        self.assertFalse(heavy)

    def test_verify_aggregate_blocks_failures_cancels_and_unexpected_skips(self):
        self.assertTrue(verify_aggregate(
            run_heavy=True,
            plan_result="success",
            regression_result="success",
            container_result="success",
            browser_result="success",
        )[0])
        self.assertTrue(verify_aggregate(
            run_heavy=False,
            plan_result="success",
            regression_result="success",
            container_result="skipped",
            browser_result="skipped",
        )[0])
        self.assertFalse(verify_aggregate(
            run_heavy=True,
            plan_result="success",
            regression_result="success",
            container_result="skipped",
            browser_result="success",
        )[0])
        self.assertFalse(verify_aggregate(
            run_heavy=True,
            plan_result="success",
            regression_result="success",
            container_result="failure",
            browser_result="success",
        )[0])
        self.assertFalse(verify_aggregate(
            run_heavy=False,
            plan_result="success",
            regression_result="cancelled",
            container_result="skipped",
            browser_result="skipped",
        )[0])

    def test_cli_writes_github_output_and_enforces_aggregate_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "gh_output.txt"
            prev = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = str(out_file)
            try:
                rc = main(["plan", "--event-name", "push", "--is-draft", "false"])
                self.assertEqual(rc, 0)
                self.assertEqual(out_file.read_text(encoding="utf-8").strip(), "run_heavy=true")
            finally:
                if prev is None:
                    os.environ.pop("GITHUB_OUTPUT", None)
                else:
                    os.environ["GITHUB_OUTPUT"] = prev

        self.assertEqual(main([
            "verify", "--run-heavy", "false",
            "--plan-result", "success", "--regression-result", "success",
            "--container-result", "skipped", "--browser-result", "skipped",
        ]), 0)
        self.assertEqual(main([
            "verify", "--run-heavy", "true",
            "--plan-result", "success", "--regression-result", "success",
            "--container-result", "skipped", "--browser-result", "success",
        ]), 1)

    def test_git_changed_files_returns_none_on_missing_or_failed_diff(self):
        self.assertIsNone(git_changed_files("", "abc"))
        self.assertIsNone(git_changed_files("abc", ""))
        failed = subprocess.CompletedProcess(["git"], 128, stdout="", stderr="bad rev")
        with patch("tools.ci_security_plan.subprocess.run", return_value=failed):
            self.assertIsNone(git_changed_files("base", "head"))

        ok_cat = subprocess.CompletedProcess(["git"], 0, stdout="")
        ok_diff = subprocess.CompletedProcess(["git"], 0, stdout="AGENTS.md\ntools/rl_wait_guard.py\n")
        with patch("tools.ci_security_plan.subprocess.run", side_effect=[ok_cat, ok_cat, ok_diff]):
            self.assertEqual(
                git_changed_files("base", "head"),
                ["AGENTS.md", "tools/rl_wait_guard.py"],
            )

    def test_select_diff_range_uses_incremental_range_only_on_valid_synchronize(self):
        self.assertEqual(
            select_diff_range(
                event_action="synchronize",
                base_sha="base", head_sha="head",
                before_sha="prev", after_sha="curr",
            ),
            ("prev", "curr"),
        )
        for action, before, after in (
            ("opened", "prev", "curr"),
            ("ready_for_review", "prev", "curr"),
            ("synchronize", ZERO_SHA, "curr"),
            ("synchronize", "", "curr"),
        ):
            self.assertEqual(
                select_diff_range(
                    event_action=action,
                    base_sha="base", head_sha="head",
                    before_sha=before, after_sha=after,
                ),
                ("base", "head"),
            )

    def test_security_regression_workflow_preserves_pins_gates_and_ready_trigger(self):
        workflow_path = ROOT / ".github" / "workflows" / "security-regression.yml"
        text = workflow_path.read_text(encoding="utf-8")
        uses_refs = re.findall(r"uses:\s*([^\s#]+)", text)
        self.assertGreaterEqual(len(uses_refs), 10)
        for ref in uses_refs:
            self.assertRegex(ref, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$", ref)

        for required_snippet in (
            "ready_for_review",
            "pip_audit",
            "gitleaks",
            "test_proxy_gateway.py",
            "stage7_container_smoke.py",
            "test_real_enospc.py",
            "tests/security_browser.cjs",
            "tests/browser_meta_editor_smoke.cjs",
            "tests/browser_missing_analysis.cjs",
            "tests/browser_sandbox.cjs",
            "check_image_vulnerabilities.py",
            "security-regression:",
            "ci_security_plan.py verify",
        ):
            self.assertIn(required_snippet, text)
