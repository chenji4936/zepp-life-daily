"""No GitHub token, real account, Zepp request or artifact upload is used."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import github_daily as job
from zepp_client import Auth, UpstreamError

TZ8 = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 27, 12, 7, tzinfo=TZ8)
DATE = '2026-09-27'
NAME = 'zepp-daily-reserved-' + DATE


class Response:
    def __init__(self, obj): self.data = io.BytesIO(json.dumps(obj).encode())
    def __enter__(self): return self.data
    def __exit__(self, *_): self.data.close()


def artifact(run_id=123):
    return {'name': NAME, 'expired': False, 'workflow_run': {'id': run_id}}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GITHUB_REPOSITORY': 'fake/example', 'GH_ARTIFACT_TOKEN': 'TEST-GITHUB-TOKEN',
                                           'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                           'GITHUB_EVENT_NAME': 'schedule'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.out = self.folder / 'output.txt'; self.out.write_text('')
        self.client = Mock()
        self.client.login.return_value = Auth('fake-user', 'fake-app-token', 'fake-device', 'api-mifit-cn3.zepp.com')
        self.client.read_steps.side_effect = [{'steps': []}, {'steps': [12000]}]
        self.client.upload.return_value = {'accepted': True, 'upstreamCode': 1}

    def test_schedule_window_is_utc8_noon_to_midnight_exclusive(self):
        for hour, minute in [(0,0),(11,59)]:
            with self.assertRaisesRegex(RuntimeError, 'OUTSIDE_1200_2359_UTC8'):
                job.today_in_window(NOW.replace(hour=hour, minute=minute))
        for hour, minute in [(12,0),(16,7),(22,0),(23,59)]:
            self.assertEqual(job.today_in_window(NOW.replace(hour=hour,minute=minute)), DATE)
        with self.assertRaisesRegex(RuntimeError, 'OUTSIDE_1200_2359_UTC8'):
            job.today_in_window(NOW+timedelta(hours=12))

    def test_artifact_api_validates_exact_name_and_same_run(self):
        seen=[]
        def opener(request, timeout):
            seen.append(request)
            return Response({'total_count':1,'artifacts':[artifact()]})
        self.assertTrue(job.check_artifact(NAME, opener=opener, expected_run_id=123))
        self.assertFalse(job.check_artifact(NAME, opener=opener, expected_run_id=124))
        self.assertIn('name=zepp-daily-reserved-2026-09-27',seen[0].full_url)
        self.assertIn('Bearer TEST-GITHUB-TOKEN',seen[0].get_header('Authorization'))
        self.assertEqual(seen[0].get_method(),'GET')
        self.assertFalse(job.check_artifact(NAME, opener=lambda *_args, **_kwargs: Response({'total_count':1,
                         'artifacts':[{'name':NAME,'expired':True,'workflow_run':{'id':123}}]})))

    def test_api_failure_cannot_be_interpreted_as_no_marker(self):
        def fail(*_args, **_kwargs): raise TimeoutError('secret-prefix-not-to-print')
        with self.assertRaisesRegex(RuntimeError,'GITHUB_ARTIFACT_CHECK_UNAVAILABLE'):
            job.reserve(now=NOW,opener=fail,runner_temp=self.folder,output_path=self.out)
        self.assertEqual(self.out.read_text(),'')
        self.assertFalse((self.folder/'zepp-daily-reservation.json').exists())

    def test_reserve_writes_only_redacted_marker_before_network_job(self):
        r=job.reserve(now=NOW,opener=lambda *_args, **_kwargs: Response({'total_count':0,'artifacts':[]}),
                      runner_temp=self.folder,output_path=self.out,choose=lambda:12000)
        self.assertEqual(r['status'],'reserved_pending_artifact_upload')
        marker=json.loads((self.folder/'zepp-daily-reservation.json').read_text())
        self.assertEqual(marker,{'date':DATE,'target':12000,'reserved':True})
        self.assertEqual(self.out.read_text(),'date=2026-09-27\ntarget=12000\nshould_run=true\n')
        self.assertNotIn('TEST-GITHUB-TOKEN',json.dumps(marker))

    def test_existing_marker_prevents_new_target_or_upload(self):
        choose=Mock(side_effect=AssertionError('should never run'))
        r=job.reserve(now=NOW,opener=lambda *_args,**_kwargs:Response({'total_count':1,'artifacts':[artifact()]}),
                      runner_temp=self.folder,output_path=self.out,choose=choose)
        self.assertEqual(r['status'],'already_reserved')
        self.assertEqual(self.out.read_text(),'')
        choose.assert_not_called()

    def test_rerun_attempt_cannot_reserve_or_write(self):
        os.environ['GITHUB_RUN_ATTEMPT']='2'
        r=job.reserve(now=NOW,opener=Mock(side_effect=AssertionError('API should not run')))
        self.assertEqual(r['status'],'rerun_blocked')
        with self.assertRaisesRegex(RuntimeError,'RERUN_BLOCKED'):
            job.upload(now=NOW, client=self.client,date=DATE,target=12000,account='test@example.invalid',password='fake')
        self.client.login.assert_not_called()

    def test_manual_dispatch_is_dry_run_only(self):
        os.environ['GITHUB_EVENT_NAME']='workflow_dispatch'
        os.environ['DAILY_DRY_RUN']='false' # Even a spoofed input cannot enable a manual write.
        with patch.object(job, 'reserve', side_effect=AssertionError('no reservation')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(job.main(['reserve']),0)
            self.assertIn('manual_dry_run',output.getvalue())
        self.client.login.assert_not_called()

    def test_upload_requires_same_run_artifact_before_any_secrets_or_zepp(self):
        with patch.object(job,'check_artifact',return_value=False) as guard:
            with self.assertRaisesRegex(RuntimeError,'CURRENT_RUN_RESERVATION_MISSING'):
                job.upload(now=NOW,client=self.client,date=DATE,target=12000,account='test@example.invalid',password='fake')
            guard.assert_called_once_with(NAME,expected_run_id='123')
        self.client.login.assert_not_called()

    def _run(self, **kwargs):
        with patch.object(job,'check_artifact',return_value=True):
            return job.upload(now=NOW,client=self.client,date=DATE,target=12000,
                              account='test@example.invalid',password='FAKE-ONLY',**kwargs)

    def test_frozen_target_upload_once_and_readback_does_not_verify_wechat(self):
        result=self._run()
        self.assertEqual(result,{'status':'cloud_matched_wechat_unverified','date':DATE,'target':12000})
        self.assertEqual(self.client.upload.call_count,1)
        record=self.client.upload.call_args.args[1]
        self.assertEqual(json.loads(record[0]['summary'])['stp']['ttl'],12000)
        self.assertEqual(record[0]['data'][0]['did'],'fake-device')
        self.assertNotIn('FAKE-ONLY',json.dumps(result))

    def test_cloud_already_higher_skips_write(self):
        self.client.read_steps.side_effect=[{'steps':[13000]}]
        self.assertEqual(self._run()['status'],'skipped_existing_not_lower')
        self.client.upload.assert_not_called()

    def test_cloud_equal_skips_write(self):
        self.client.read_steps.side_effect=[{'steps':[12000]}]
        self.assertEqual(self._run()['status'],'skipped_existing_not_lower')
        self.client.upload.assert_not_called()

    def test_initial_read_error_does_not_write(self):
        self.client.read_steps.side_effect=UpstreamError('UPSTREAM_TIMEOUT','verify')
        with self.assertRaises(UpstreamError): self._run()
        self.client.upload.assert_not_called()

    def test_write_timeout_never_retries(self):
        self.client.upload.side_effect=UpstreamError('UPSTREAM_TIMEOUT','upload',uncertain=True)
        with self.assertRaises(UpstreamError): self._run()
        self.assertEqual(self.client.upload.call_count,1)

    def test_after_read_failure_keeps_accepted_not_cloud_verified(self):
        self.client.read_steps.side_effect=[{'steps':[]}, UpstreamError('UPSTREAM_TIMEOUT','verify')]
        self.assertEqual(self._run()['status'],'accepted_readback_unverified')
        self.assertEqual(self.client.upload.call_count,1)

    def test_empty_credentials_or_bad_target_fail_before_network(self):
        with self.assertRaisesRegex(RuntimeError,'GITHUB_SECRETS_MISSING'):
            with patch.object(job,'check_artifact',return_value=True):
                job.upload(now=NOW,client=self.client,date=DATE,target=12000,account='',password='')
        with self.assertRaisesRegex(RuntimeError,'INVALID_TARGET'):
            job.upload(now=NOW,client=self.client,date=DATE,target=13001)
        self.client.login.assert_not_called()

    def test_expired_date_fails_before_network(self):
        with self.assertRaisesRegex(RuntimeError,'DATE_CHANGED_OR_OUTSIDE_WINDOW'):
            job.upload(now=NOW+timedelta(days=1),client=self.client,date=DATE,target=12000)
        self.client.login.assert_not_called()


if __name__ == '__main__': unittest.main()
