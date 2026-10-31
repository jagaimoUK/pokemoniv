import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('image_audit', Path(__file__).resolve().parents[1] / 'tools/check_image_vulnerabilities.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ImageAuditTests(unittest.TestCase):
    def test_no_findings_passes(self):
        self.assertFalse(audit.summarize({'Results': [{'Vulnerabilities': None}]})[1])

    def test_fixable_critical_and_high_block(self):
        for severity in ('HIGH', 'CRITICAL'):
            text, blocked = audit.summarize({'Results': [{'Vulnerabilities': [{
                'Severity': severity, 'VulnerabilityID': 'CVE-fixture',
                'PkgName': 'example', 'FixedVersion': '2'}]}]})
            self.assertTrue(blocked)
            self.assertIn('CVE-fixture', text)

    def test_unfixed_high_is_visible_and_low_does_not_block(self):
        text, blocked = audit.summarize({'Results': [{'Vulnerabilities': [
            {'Severity': 'HIGH', 'VulnerabilityID': 'CVE-unfixed'},
            {'Severity': 'LOW', 'FixedVersion': '2'}]}]})
        self.assertFalse(blocked)
        self.assertIn('CVE-unfixed', text)
        self.assertIn('LOW', text)
