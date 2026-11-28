"""Offline tests for event-trigger and update safety; no network calls."""
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pvpoke_event_sync as sync


class EventSyncTests(unittest.TestCase):
    def test_ics_utc_jst_and_folding(self):
        ics = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
               b"SUMMARY:Community\r\n Day\r\n"
               b"DTSTART:20261121T050000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        events = sync.read_event_starts(ics)
        self.assertEqual(events[0]["name"], "CommunityDay")
        starts = sync.relevant_events(events, datetime(2026, 11, 21, 6, tzinfo=timezone.utc))
        self.assertEqual(starts[0]["start_jst"], "2026-11-21T14:00:00+09:00")

    def test_day_and_long_season(self):
        ics = (b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Season\n"
               b"DTSTART;VALUE=DATE:20260901\n"
               b"DTEND;VALUE=DATE:20261201\nEND:VEVENT\nEND:VCALENDAR")
        events = sync.read_event_starts(ics)
        self.assertFalse(sync.relevant_events(events, datetime(2026, 10, 13, tzinfo=timezone.utc)))
        self.assertTrue(sync.relevant_events(events, datetime(2026, 8, 31, tzinfo=timezone.utc)))

    def test_weekly_fallback_and_force(self):
        tuesday = datetime(2026, 11, 24, 4, tzinfo=timezone.utc)
        self.assertFalse(sync.eligible(tuesday, [])[0])
        self.assertTrue(sync.eligible(tuesday, [], force=True)[0])
        monday = datetime(2026, 11, 23, 4, tzinfo=timezone.utc)
        self.assertTrue(sync.eligible(monday, [])[0])

    def test_invalid_ics_does_not_pass(self):
        with self.assertRaises(ValueError):
            sync.read_event_starts(b"not an ICS")

    def test_recommendation_is_validated_against_gm(self):
        pokemon = []
        for i in range(101):
            pokemon.append({"speciesId": f"test{i}", "fastMoves": ["FAST"],
                            "chargedMoves": ["ONE", "TWO"], "tags": []})
        gm = {"pokemon": pokemon}
        rankings = [{"speciesId": f"test{i}", "moveset": ["FAST", "ONE", "TWO"]}
                    for i in range(101)]
        ranks = sync.load_recommended(json.dumps(rankings).encode(), gm)
        self.assertEqual(len(ranks), 101)
        rankings[0]["moveset"] = ["FAST", "ONE", "NOT_LEGAL"]
        self.assertEqual(len(sync.load_recommended(json.dumps(rankings).encode(), gm)), 100)

    def test_pins_are_replaced_only_at_known_locations(self):
        original = """COMMIT = '1111111111111111111111111111111111111111'
FILES = {
    'gamemaster.json': ('data/gamemaster.json', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
    'Pokemon.js': ('js/pokemon/Pokemon.js', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'),
}
"""
        changed = sync.updated_snapshot(original, "2" * 40,
                         {"gamemaster.json": "c" * 64, "Pokemon.js": "d" * 64})
        self.assertIn("'gamemaster.json': ('data/gamemaster.json', '" + "c" * 64, changed)
        self.assertIn("COMMIT = '" + "2" * 40 + "'", changed)
        with self.assertRaises(ValueError):
            sync.updated_snapshot("COMMIT = 0", "2" * 40, {"gamemaster.json": "c" * 64,
                                                            "Pokemon.js": "d" * 64})


    def test_download_authorization_header(self):
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_secret_test_token"}):
            sync.download("https://api.github.com/repos/pvpoke/pvpoke/commits/master")
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.headers.get("Authorization"), "Bearer ghp_secret_test_token")

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen, \
             patch.dict("os.environ", {}, clear=True):
            sync.download("https://api.github.com/repos/pvpoke/pvpoke/commits/master")
            req = mock_urlopen.call_args[0][0]
            self.assertIsNone(req.headers.get("Authorization"))

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_secret_test_token"}):
            sync.download("https://raw.githubusercontent.com/test.json")
            req = mock_urlopen.call_args[0][0]
            self.assertIsNone(req.headers.get("Authorization"))


if __name__ == "__main__":
    unittest.main()

