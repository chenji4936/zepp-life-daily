"""Static workflow checks; no third-party YAML dependency on runner."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
YAML = (ROOT / '.github/workflows/zepp-daily.yml').read_text(encoding='utf-8')


class WorkflowTests(unittest.TestCase):
    def test_expected_utc_window_and_two_phase_structure(self):
        self.assertIn("cron: '7 4,8,12,15 * * *'", YAML)
        self.assertIn('workflow_dispatch:', YAML)
        self.assertIn('cancel-in-progress: false', YAML)
        self.assertIn('  reserve:', YAML)
        self.assertIn('  upload:', YAML)
        self.assertIn('needs: reserve', YAML)
        self.assertIn("if: needs.reserve.outputs.should_run == 'true' && github.run_attempt == 1", YAML)

    def test_marker_upload_step_precedes_zepp_job(self):
        marker = YAML.index('actions/upload-artifact@v4')
        zepp = YAML.index('  upload:')
        self.assertLess(marker, zepp)
        self.assertIn('if-no-files-found: error', YAML)
        self.assertIn('retention-days: 7', YAML)
        self.assertIn('GH_ARTIFACT_TOKEN: ${{ github.token }}', YAML)

    def test_secrets_only_in_zepp_job_and_no_untrusted_triggers(self):
        first, second = YAML.split('\n  upload:', 1)
        self.assertNotIn('secrets.ZEPP_ACCOUNT', first)
        self.assertNotIn('secrets.ZEPP_PASSWORD', first)
        self.assertIn('ZEPP_ACCOUNT: ${{ secrets.ZEPP_ACCOUNT }}', second)
        self.assertIn('ZEPP_PASSWORD: ${{ secrets.ZEPP_PASSWORD }}', second)
        self.assertNotRegex(YAML, r'(?m)^\s+pull_request(_target)?:')
        self.assertNotRegex(YAML, r'(?m)^\s+workflow_run:')
        self.assertNotRegex(YAML, r'(?m)^\s+push:')
        self.assertIn('persist-credentials: false', YAML)
        self.assertIn('actions: read', YAML)


if __name__ == '__main__': unittest.main()
