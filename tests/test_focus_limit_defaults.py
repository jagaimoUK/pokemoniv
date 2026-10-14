"""Omitted focus_limit returns up to 20 variants; explicit limits survive."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import pvpoke_bridge_core as bridge
import pvpoke_iv_workflow as workflow_module
from pvpoke_iv_workflow import IVWorkflow
from pvpoke_selection_digest import build_selection_digest
from test_iv_workflow import CANDIDATE, IVS, FakeBackend
from test_selection_digest import sample_zip

ROOT = Path(__file__).resolve().parents[1]
FOCUS = ["Corsola", "Tinkaton", "Opponent_"]


class FocusLimitDefaultsTests(unittest.TestCase):
    def test_digest_default_returns_twenty_variants_without_losing_ratings(self):
        with ZipFile(sample_zip(opponents=21)) as archive:
            report = build_selection_digest(archive, focus_opponents=FOCUS)
        self.assertEqual(report["focus_matchups_total"], 21)
        self.assertEqual(report["focus_matchups_returned"], 20)
        self.assertTrue(report["focus_matchups_truncated"])
        self.assertTrue(report["complete"])
        self.assertEqual(report["total_ratings_checked"], 2 * 21 * 6)
        self.assertEqual(report["candidate_evidence_count"], 2)

    def test_explicit_limits_include_zero(self):
        for limit in (0, 3):
            with self.subTest(limit=limit), ZipFile(sample_zip(opponents=21)) as archive:
                report = build_selection_digest(
                    archive, focus_opponents=FOCUS, focus_limit=limit)
                self.assertEqual(report["focus_matchups_returned"], limit)
                self.assertEqual(report["total_ratings_checked"], 2 * 21 * 6)

    def test_bridge_omission_and_explicit_override(self):
        for limit, expected in ((None, 20), (0, 0), (3, 3)):
            options = {} if limit is None else {"focus_limit": limit}
            with self.subTest(limit=limit), patch.object(
                    bridge, "_zip", side_effect=lambda: ZipFile(sample_zip(opponents=21))):
                report = bridge.selection_digest(focus_opponents=FOCUS, **options)
                self.assertEqual(report["focus_matchups_returned"], expected)

    def test_workflow_preserves_limit_through_polling(self):
        for limit, expected in ((None, 20), (0, 0), (3, 3)):
            backend = FakeBackend()
            workflow = IVWorkflow(backend)
            options = {} if limit is None else {"focus_limit": limit}
            started = workflow.run(CANDIDATE, IVS, wait_seconds=0, **options)
            backend.state = "done"
            with self.subTest(limit=limit), patch.object(
                    workflow_module, "build_selection_digest",
                    wraps=build_selection_digest) as build:
                report = workflow.result(started["run_ref"])
                self.assertTrue(report["complete"])
                self.assertEqual(build.call_args.args[5], expected)
                self.assertEqual(backend.run_count, 1)

    def test_mcp_schema_and_dispatch_omission_and_override(self):
        # Execute only the actual schema and dispatcher, without starting an
        # authenticated HTTP server or a live battle in this regression test.
        source = ast.parse((ROOT / "pvpoke_mcp_remote.py").read_text())
        selected = []
        for node in source.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in {
                        "POKEMON", "OPPONENT", "PREP", "TOOLS"}
                    for target in node.targets):
                selected.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name == "call_tool":
                selected.append(node)
        backend, runner = Mock(), Mock()
        namespace = {"backend": backend, "IV_RUNNER": runner}
        exec(compile(ast.Module(body=selected, type_ignores=[]),
                     "mcp_focus_limit_dispatch", "exec"), namespace)
        schemas = {tool["name"]: tool for tool in namespace["TOOLS"]}
        for name in ("get_selection_digest", "run_iv_selection"):
            self.assertEqual(
                schemas[name]["inputSchema"]["properties"]["focus_limit"]["default"], 20)
            for limit, expected in ((None, 20), (0, 0), (3, 3)):
                args = {"candidate": CANDIDATE, "ivs": IVS}
                if limit is not None:
                    args["focus_limit"] = limit
                with self.subTest(tool=name, limit=limit):
                    namespace["call_tool"](name, args)
                    call = backend.selection_digest if name == "get_selection_digest" else runner.run
                    position = 4 if name == "get_selection_digest" else 6
                    self.assertEqual(call.call_args.args[position], expected)


if __name__ == "__main__":
    unittest.main()
