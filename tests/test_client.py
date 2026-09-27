"""All tests are offline: no requests reach Zepp or any external server."""
import json
import base64
import unittest
from unittest.mock import patch
import requests
from zepp_client import Auth, ZeppClient, UpstreamError, normalize_account, mask_account, summary_record, retry_seconds, select_data_host, parse_step_values


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.mounts = []
        self.trust_env = True
    def mount(self, *args): self.mounts.append(args)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception): raise item
        return item


class ClientTests(unittest.TestCase):
    def client(self, responses):
        session = FakeSession(responses)
        return ZeppClient(lambda: session), session

    def test_account_normalization_preserves_country_code(self):
        self.assertEqual(normalize_account(' test@example.invalid '), 'test@example.invalid')
        self.assertEqual(normalize_account('+6581234567'), '+6581234567')
        self.assertEqual(normalize_account('+8613812345678'), '+8613812345678')
        for value in ('13812345678', 'not email', '', None, 'x\n@example.invalid'):
            with self.assertRaises(ValueError): normalize_account(value)

    def test_mask_account(self):
        self.assertEqual(mask_account('alice@example.invalid'), 'al•••@example.invalid')
        self.assertNotIn('81234567', mask_account('+6581234567'))

    def test_minimal_payload_has_no_unrelated_health_metrics(self):
        record = summary_record('2026-09-26', 12000)
        self.assertEqual(len(record[0]['data']), 1)
        raw = base64.b64decode(record[0]['data'][0]['value'])
        self.assertEqual(len(raw), 4320)
        self.assertEqual(sum(raw[2::3]), 12000)
        self.assertEqual(set(raw[::3]), {1, 127})
        summary = json.loads(record[0]['summary'])
        self.assertEqual(summary['stp'], {'ttl': 12000})
        self.assertNotIn('slp', summary)
        self.assertNotIn('data_hr', record[0])
        self.assertNotIn('cal', summary['stp'])
        self.assertNotIn('dis', summary['stp'])

    def test_full_login_sequence_correct_id_and_no_password_in_url(self):
        client, s = self.client([
            Response({'access': 'fake-access-code-for-test'}),
            Response({'token_info': {'login_token': 'fake-login-token', 'user_id': 'test-user-id'}}),
            Response({'token_info': {'app_token': 'fake-app-token'}}),
        ])
        auth = client.login('test@example.invalid', 'SENSITIVE-FAKE-PASSWORD')
        self.assertEqual(auth.user_id, 'test-user-id')
        self.assertEqual(auth.app_token, 'fake-app-token')
        self.assertEqual(len(s.calls), 3)
        self.assertEqual([c[0] for c in s.calls], ['POST', 'POST', 'GET'])
        self.assertFalse(s.trust_env)
        self.assertNotIn('SENSITIVE-FAKE-PASSWORD', ''.join(c[1] for c in s.calls))
        self.assertEqual(s.calls[0][2]['data']['password'], 'SENSITIVE-FAKE-PASSWORD')
        for _, _, kwargs in s.calls:
            self.assertTrue(kwargs['verify'])
            self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(s.mounts[0][1].max_retries.total, 0)
        self.assertNotIn('fake-app-token', repr(auth))

    def test_login_accepts_redirect_without_following_it(self):
        client, s = self.client([
            Response(status=302, headers={'Location': 'https://example.invalid/?access=fake-access&state=x'}),
            Response({'token_info': {'login_token': 'fake-login', 'user_id': 42}}),
            Response({'token_info': {'app_token': 'fake-app'}}),
        ])
        self.assertEqual(client.login('test@example.invalid', 'fake').user_id, '42')
        self.assertEqual(len(s.calls), 3)
        self.assertTrue(all('https://example.invalid/' not in c[1] for c in s.calls))

    def test_login_code_zero_is_not_a_credential(self):
        client, s = self.client([Response({'code': 0})])
        with self.assertRaises(UpstreamError) as caught: client.login('test@example.invalid', 'fake')
        self.assertEqual(caught.exception.code, 'LOGIN_RESPONSE')
        self.assertEqual(len(s.calls), 1)

    def test_upload_uses_user_id_not_login_token_and_fixed_payload(self):
        client, s = self.client([Response({'code': 1, 'private': 'NEVER-RETURN-THIS'})])
        record = summary_record('2026-09-26', 12345)
        result = client.upload(Auth('correct-user-id', 'fake-app-token', 'fake-device-id'), record)
        call = s.calls[0]
        self.assertEqual(call[0], 'POST')
        self.assertEqual(call[2]['data']['userid'], 'correct-user-id')
        self.assertEqual(call[2]['headers']['apptoken'], 'fake-app-token')
        self.assertEqual(json.loads(call[2]['data']['data_json']), record)
        self.assertTrue(result['accepted'])
        self.assertFalse(result['effectVerified'])
        self.assertNotIn('NEVER-RETURN-THIS', json.dumps(result))

    def test_only_integer_acceptance_code_one_is_accepted(self):
        for code in (0, 2, '1', None, True, 1.0):
            client, _ = self.client([Response({'code': code})])
            with self.assertRaises(UpstreamError) as caught:
                client.upload(Auth('u', 'a', 'd'), summary_record('2026-09-26', 42))
            self.assertEqual(caught.exception.code, 'UPLOAD_REJECTED')

    def test_upload_timeout_is_uncertain_and_not_retried(self):
        client, s = self.client([requests.Timeout('private-token=SHOULD-NOT-LEAK')])
        with self.assertRaises(UpstreamError) as caught:
            client.upload(Auth('u', 'a', 'd'), summary_record('2026-09-26', 42))
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn('SHOULD-NOT-LEAK', str(caught.exception))
        self.assertEqual(len(s.calls), 1)

    def test_upload_malformed_response_is_uncertain(self):
        client, _ = self.client([Response(ValueError('secret-content'))])
        with self.assertRaises(UpstreamError) as caught:
            client.upload(Auth('u', 'a', 'd'), summary_record('2026-09-26', 42))
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn('secret-content', str(caught.exception))

    def test_429_honors_retry_after_without_retry(self):
        client, s = self.client([Response({'private': 'secret'}, status=429, headers={'Retry-After': '123'})])
        with self.assertRaises(UpstreamError) as caught: client.login('test@example.invalid', 'fake')
        self.assertEqual(caught.exception.retry_after, 123)
        self.assertEqual(caught.exception.code, 'RATE_LIMITED')
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(retry_seconds(None), 900)
        self.assertEqual(retry_seconds('invalid'), 900)

    def test_unexpected_upload_redirect_is_not_success(self):
        client, s = self.client([Response({'code': 1}, status=302, headers={'Location': 'https://evil.invalid'})])
        with self.assertRaises(UpstreamError): client.upload(Auth('u', 'a', 'd'), [])
        self.assertEqual(len(s.calls), 1)

    def test_endpoint_allowlist_blocks_non_official_requests(self):
        client, s = self.client([])
        with self.assertRaises(UpstreamError) as caught:
            client._request(s, 'POST', 'https://evil.invalid/', 'login')
        self.assertEqual(caught.exception.code, 'ENDPOINT_BLOCKED')
        self.assertEqual(len(s.calls), 0)


    def test_readback_supports_observed_date_time_field(self):
        summary = base64.b64encode(b'{"stp":{"ttl":12000}}').decode()
        for date in ('2026-09-27', '2026-09-27T00:00:00+08:00'):
            self.assertEqual(parse_step_values({'data':[{'date_time':date,'summary':summary}]}, '2026-09-27'), [12000])
        self.assertEqual(parse_step_values({'data':[{'date_time':'2026-09-26','summary':summary}]}, '2026-09-27'), [])

    def test_invalid_region_metadata_is_ignored(self):
        for value in ('api-mifit-cn3.zepp.com:bad', 'https://user:pass@api-mifit-cn3.zepp.com',
                      'https://api-mifit-cn3.zepp.com/?secret=not-valid', 'http://[bad'):
            self.assertEqual(select_data_host({'domains':[value]}), 'api-mifit.zepp.com')

    def test_data_host_comes_from_login_region_not_hardcoded_cn2(self):
        response = {'domains': {'api-mifit.zepp.com': 'api-mifit-cn3.zepp.com', 'auth.zepp.com': 'auth-cn3.zepp.com'}}
        self.assertEqual(select_data_host(response), 'api-mifit-cn3.zepp.com')
        self.assertEqual(select_data_host({}), 'api-mifit.zepp.com')
        self.assertEqual(select_data_host({'domains': {'api-mifit.zepp.com': 'https://evil.invalid/'}}), 'api-mifit.zepp.com')
        self.assertEqual(select_data_host({'domains': ['api-mifit-cn3.zepp.com.evil.invalid']}), 'api-mifit.zepp.com')

    def test_login_stores_region_and_upload_uses_it(self):
        client, session = self.client([
            Response({'access': 'fake-access-for-tests'}),
            Response({'token_info': {'login_token': 'fake-login', 'user_id': 'uid'}, 'domains': {'api-mifit.zepp.com': 'api-mifit-cn3.zepp.com'}}),
            Response({'token_info': {'app_token': 'fake-app'}}),
            Response({'code': 1})])
        auth = client.login('test@example.invalid', 'fake-password')
        self.assertEqual(auth.data_host, 'api-mifit-cn3.zepp.com')
        client.upload(auth, summary_record('2026-09-27', 12000, auth.device_id))
        self.assertEqual(session.calls[-1][1], 'https://api-mifit-cn3.zepp.com/v1/data/band_data.json')
        self.assertEqual(session.calls[-1][2]['timeout'], (20, 30))

    def test_login_preserves_safe_business_error_code_only(self):
        client, _ = self.client([Response({'access': 'fake-access'}), Response({'error_code': -1234, 'secret': 'NOT-TO-EXPOSE'})])
        with self.assertRaises(UpstreamError) as caught: client.login('test@example.invalid', 'fake')
        self.assertEqual(caught.exception.business_code, -1234)
        self.assertNotIn('NOT-TO-EXPOSE', str(caught.exception))

    def test_minute_steps_match_total_at_range_edges(self):
        for steps in (1, 100, 101, 12000, 98800):
            r = summary_record('2026-09-27', steps, 'fake-device', minute_of_day=1)[0]
            raw = base64.b64decode(r['data'][0]['value'])
            self.assertEqual(sum(raw[2::3]), steps)
            self.assertEqual(len(raw), 1440 * 3)
            self.assertEqual(r['data'][0]['did'], 'fake-device')
            self.assertNotIn('data_hr', r)
            self.assertNotIn('slp', json.loads(r['summary']))

    def test_readback_decodes_only_requested_day(self):
        encoded = base64.b64encode(json.dumps({'stp': {'ttl': 12000}, 'slp': {'private': 'NOT-TO-EXPOSE'}}).encode()).decode()
        data = {'code': 1, 'data': [{'date': '2026-09-27', 'summary': encoded}, {'date': '2026-09-26', 'summary': encoded}]}
        self.assertEqual(parse_step_values(data, '2026-09-27'), [12000])
        client, session = self.client([Response(data)])
        result = client.read_steps(Auth('uid', 'fake-app', 'device', 'api-mifit-cn3.zepp.com'), '2026-09-27')
        self.assertEqual(result['steps'], [12000])
        self.assertEqual(session.calls[0][0], 'GET')
        self.assertNotIn('NOT-TO-EXPOSE', json.dumps(result))

    def test_empty_cloud_record_is_not_treated_as_zero_or_verified(self):
        client, _ = self.client([Response({'code': 1, 'data': []})])
        result = client.read_steps(Auth('uid', 'fake-app', 'device'), '2026-09-27')
        self.assertEqual(result['steps'], [])


if __name__ == '__main__':
    unittest.main()
