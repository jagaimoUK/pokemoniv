"""Regression tests: missing batch_mode means simple; explicit detailed survives."""
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

import pvpoke_bridge_core as bridge
import pvpoke_24_workflow as workflow
import pvpoke_mcp_remote as remote

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = dict(species="quagsire", fast="MUD_SHOT",
                 charged1="AQUA_TAIL", charged2="STONE_EDGE")


class BatchModeDefaultsTests(unittest.TestCase):
    def test_bridge_default_is_simple(self):
        self.assertEqual(bridge.validate_24(CANDIDATE, "0,11,12")["batch_mode"], "simple")
        self.assertEqual(bridge.validate_24(CANDIDATE, "0,11,12", "detailed")["batch_mode"], "detailed")
        self.assertEqual(inspect.signature(bridge.start24).parameters["batch_mode"].default, "simple")
        self.assertEqual(inspect.signature(bridge.preview24).parameters["batch_mode"].default, "simple")

    def test_remote_schema_defaults_and_handlers(self):
        for name in ("prepare_24_conditions", "start_24_conditions"):
            schema = next(t["inputSchema"] for t in remote.TOOLS if t["name"] == name)
            self.assertEqual(schema["properties"]["batch_mode"]["default"], "simple")
            self.assertEqual(schema["properties"]["batch_mode"]["enum"], ["simple", "detailed"])
        with patch.object(remote.backend, "preview24", return_value={"ok":True}) as preview:
            remote.call_tool("prepare_24_conditions", {"candidate": CANDIDATE, "ivs": "0,11,12"})
            self.assertEqual(preview.call_args.args[-1], "simple")

    def test_web_ui_initial_state_and_api_fallback(self):
        source = (ROOT / "pvpoke_web.py").read_text(encoding="utf-8")
        self.assertIn('<select id="batchMode"><option value="simple">', source)
        self.assertIn("str(payload.get('batch_mode') or 'simple')", source)
        self.assertIn("def background_run(shields, batch24=False, batch_mode='simple'):", source)

    def test_cli_default_and_explicit_override(self):
        source = (ROOT / "pvpoke_24_workflow.py").read_text(encoding="utf-8")
        self.assertIn("default='simple'", source)
        self.assertEqual(workflow.BATCH_MODES["simple"], ("default",))
        self.assertEqual(len(workflow.BATCH_MODES["detailed"]), 4)


if __name__ == "__main__":
    unittest.main()
