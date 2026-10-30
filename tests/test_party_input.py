import subprocess
import unittest
from pathlib import Path

class PartyInputTests(unittest.TestCase):
    def test_name_and_default_move_contract(self):
        r=subprocess.run(['node','tests/test_party_input.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
