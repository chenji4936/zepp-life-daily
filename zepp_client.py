"""Unofficial Zepp/Huami adapter. No background jobs, retries, or credential logs.

API formats are based on public implementations credited in THIRD_PARTY_NOTICES.md.
Use the data region returned at login, synthesize step-only minute data, and
separately report upload acceptance and read-back verification. No heart/sleep
samples are generated, and WeChat display cannot be verified by this client.
"""
from __future__ import annotations

import json
import base64
import math
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, urlparse

import requests
from requests.adapters import HTTPAdapter

APP_NAME = "com.huami.midong"
DN = (
    "api-mifit.zepp.com,api-user.zepp.com,api-mifit.zepp.com,"
    "api-watch.zepp.com,app-analytics.zepp.com,auth.zepp.com,api-analytics.zepp.com"
)
REGISTRATION_URL = "https://api-user.huami.com/registrations/{account}/tokens"
CLIENT_LOGIN_URL = "https://api-mifit.zepp.com/v2/client/login"
APP_TOKEN_URL = "https://api-mifit.zepp.com/v1/client/app_tokens"
UPLOAD_URL = "https://api-mifit.zepp.com/v1/data/band_data.json"
ALLOWED_HOSTS = {"api-user.huami.com", "api-mifit.zepp.com"}


class UpstreamError(Exception):
    """Only safe, fixed messages are exposed to the browser."""

    def __init__(self, code: str, stage: str, *, status: int | None = None,
                 retry_after: int = 0, uncertain: bool = False, business_code=None):
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.status = status
        self.retry_after = retry_after
        self.uncertain = uncertain
        self.business_code = safe_business_code(business_code)


@dataclass(repr=False)
class Auth:
    user_id: str
    app_token: str
    device_id: str
    data_host: str = "api-mifit.zepp.com"


def normalize_account(account: str) -> str:
    if not isinstance(account, str):
        raise ValueError("请输入 Zepp 账号邮箱，或带国家码的手机号。")
    account = account.strip()
    if len(account) > 254 or any(ord(c) < 32 for c in account):
        raise ValueError("账号格式不正确。")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", account):
        return account
    if re.fullmatch(r"\+[1-9]\d{6,14}", account):
        return account
    raise ValueError("请填写有效邮箱；手机号必须带国家码，例如 +8613812345678。")


def mask_account(account: str) -> str:
    if "@" in account:
        local, domain = account.rsplit("@", 1)
        return local[:2] + "•••@" + domain
    return account[:3] + "••••" + account[-4:]


def safe_business_code(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[-A-Za-z0-9_]{1,48}", value):
        return value
    return None


def is_data_host(host):
    return isinstance(host, str) and re.fullmatch(r"api-mifit(?:-[a-z0-9]+)?\.(?:zepp|huami)\.com", host) is not None


def select_data_host(*responses):
    """Accept only fixed-format official data hosts from authenticated responses."""
    hosts = []
    def collect(value):
        if isinstance(value, dict):
            # Values first: keys often contain the generic logical hostname.
            for child in value.values(): collect(child)
            for key in value: collect(key)
        elif isinstance(value, list):
            for child in value: collect(child)
        elif isinstance(value, str):
            try:
                parsed = urlparse(value if "://" in value else "//" + value)
                host, port = parsed.hostname, parsed.port
            except ValueError:
                return
            if is_data_host(host) and parsed.username is None and parsed.password is None:
                if port in (None, 443) and parsed.path in ("", "/") and not parsed.query and not parsed.fragment:
                    if host not in hosts: hosts.append(host)
    for response in responses:
        if isinstance(response, dict):
            collect(response.get("domains"))
            collect(response.get("domain"))
    regional = [h for h in hosts if h.startswith("api-mifit-")]
    return regional[0] if regional else (hosts[0] if hosts else "api-mifit.zepp.com")


def summary_record(date: str, steps: int, device_id: str = "LOCAL-PREVIEW", minute_of_day=None) -> list[dict]:
    """Synthetic step-only daily record, with a nonempty valid-length data block.

    The legacy name is retained for callers. Three-byte minute samples contain
    category, activity intensity and steps; category 127 denotes no sample.
    No pulse, sleep, distance or calorie fields are generated. This is not
    measured activity. The exact snapshot is shown before explicit confirmation.
    """
    if type(steps) is not int or not 1 <= steps <= 98800:
        raise ValueError("invalid step count")
    if minute_of_day is None:
        now = datetime.now(timezone(timedelta(hours=8)))
        minute_of_day = now.hour * 60 + now.minute
    minutes = math.ceil(steps / 100)
    end = min(1439, max(minutes - 1, int(minute_of_day) - 1))
    start = end - minutes + 1
    raw = bytearray([127, 0, 0] * 1440)
    remaining = steps
    for minute in range(start, end + 1):
        count = min(100, remaining)
        remaining -= count
        raw[minute * 3:minute * 3 + 3] = bytes([1, 50, count])
    assert sum(raw[2::3]) == steps
    return [{
        "date": date,
        "data": [{"start": 0, "stop": 1439, "value": base64.b64encode(raw).decode("ascii"),
                  "tz": 32, "did": device_id, "src": 24}],
        "summary": json.dumps({"v": 6, "stp": {"ttl": steps}, "tz": "28800"},
                              ensure_ascii=False, separators=(",", ":")),
        "source": 24, "type": 0,
    }]


def parse_step_values(data, date):
    values = []
    records = data.get("data") if isinstance(data, dict) else None
    if not isinstance(records, list): return values
    for record in records:
        if not isinstance(record, dict): continue
        record_date = record.get("date", record.get("date_time"))
        if not isinstance(record_date, str) or record_date[:10] != date: continue
        summary = record.get("summary")
        if isinstance(summary, str):
            try: summary = json.loads(summary)
            except (ValueError, TypeError):
                try: summary = json.loads(base64.b64decode(summary + "=" * (-len(summary) % 4)))
                except (ValueError, TypeError, UnicodeError): continue
        if not isinstance(summary, dict): continue
        step = summary.get("stp")
        total = step.get("ttl") if isinstance(step, dict) else None
        if type(total) is int and total >= 0: values.append(total)
    return values


def retry_seconds(value: str | None) -> int:
    if value:
        try:
            return max(1, min(86400, int(value)))
        except (ValueError, TypeError, OverflowError):
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(1, min(86400, int((parsed - datetime.now(timezone.utc)).total_seconds()) + 1))
            except (ValueError, TypeError, OverflowError):
                pass
    return 900


def client_headers() -> dict[str, str]:
    return {
        "app_name": APP_NAME, "appname": APP_NAME,
        "hm-privacy-ceip": "false", "x-request-id": str(uuid.uuid4()),
        "accept-language": "zh-CN", "cv": "151689_9.12.5", "v": "2.0",
        "appplatform": "android_phone", "vb": "202509151347", "vn": "9.12.5",
        "user-agent": "Zepp/9.12.5 (2206122SC; Android 14; Density/2.625)",
        "accept": "application/json", "accept-encoding": "gzip, deflate",
    }


class ZeppClient:
    def __init__(self, session_factory=requests.Session):
        self.session_factory = session_factory

    def _session(self):
        s = self.session_factory()
        # Do not silently route credentials through environment proxies or .netrc.
        s.trust_env = False
        s.mount("https://", HTTPAdapter(max_retries=0))
        return s

    def _request(self, session, method: str, url: str, stage: str, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname not in ALLOWED_HOSTS and not is_data_host(parsed.hostname)) or parsed.port not in (None, 443):
            raise UpstreamError("ENDPOINT_BLOCKED", stage)
        kwargs.update(timeout=(20, 30), allow_redirects=False, verify=True)
        try:
            response = session.request(method, url, **kwargs)
        except requests.Timeout:
            raise UpstreamError("UPSTREAM_TIMEOUT", stage, uncertain=stage == "upload") from None
        except requests.RequestException:
            raise UpstreamError("UPSTREAM_NETWORK", stage, uncertain=stage == "upload") from None
        status = response.status_code
        if status == 429:
            raise UpstreamError("RATE_LIMITED", stage, status=status,
                                retry_after=retry_seconds(response.headers.get("Retry-After")))
        if status in (401, 403):
            raise UpstreamError("AUTH_REJECTED", stage, status=status)
        if status >= 400:
            raise UpstreamError("UPSTREAM_HTTP", stage, status=status,
                                uncertain=stage == "upload" and status >= 500)
        if not 200 <= status < 300 and not (stage == "access" and status in (302, 303)):
            raise UpstreamError("UNEXPECTED_RESPONSE", stage, status=status, uncertain=stage == "upload")
        return response

    @staticmethod
    def _json(response, stage: str) -> dict:
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise UpstreamError("UNEXPECTED_RESPONSE", stage, status=response.status_code,
                                uncertain=stage == "upload") from None
        if not isinstance(data, dict):
            raise UpstreamError("UNEXPECTED_RESPONSE", stage, status=response.status_code,
                                uncertain=stage == "upload")
        return data

    def login(self, account: str, password: str) -> Auth:
        account = normalize_account(account)
        with self._session() as session:
            response = self._request(
                session, "POST", REGISTRATION_URL.format(account=quote(account, safe="")), "access",
                data={
                    "client_id": "HuaMi", "country_code": "CN", "json_response": "true",
                    "name": account, "password": password,
                    "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
                    "state": "REDIRECTION", "token": "access",
                },
                headers={
                    "x-request-id": str(uuid.uuid4()), "app_name": "com.huami.webapp", "lang": "zh",
                    "accept": "application/json, text/plain, */*", "accept-language": "zh-CN,zh;q=0.9",
                    "user-agent": "Mozilla/5.0", "origin": "https://user.zepp.com",
                    "referer": "https://user.zepp.com/", "dnt": "1", "accept-encoding": "gzip, deflate",
                },
            )
            access = None
            if response.status_code == 200:
                data = self._json(response, "access")
                access = data.get("access") or data.get("access_token")
                # Some documented variants return the access credential as 'code'.
                candidate = data.get("code")
                if not access and isinstance(candidate, str) and len(candidate) > 16 and not candidate.isdigit():
                    access = candidate
            elif response.status_code in (302, 303):
                params = parse_qs(urlparse(response.headers.get("Location", "")).query)
                if "error" in params:
                    raise UpstreamError("AUTH_REJECTED", "access", status=response.status_code)
                access = (params.get("access") or [None])[0]
            if not isinstance(access, str) or not access:
                raise UpstreamError("LOGIN_RESPONSE", "access", status=response.status_code)

            response = self._request(session, "POST", CLIENT_LOGIN_URL, "login", data={
                "allow_registration": "false", "app_name": APP_NAME, "app_version": "9.12.5",
                "code": access, "country_code": "CN", "device_id": str(uuid.uuid4()).upper(),
                "device_model": "android_phone", "dn": DN, "grant_type": "access_token",
                "lang": "zh", "source": "com.huami.watch.hmwatchmanager:9.12.5:151689", "third_name": "huami",
            }, headers=client_headers())
            login_data = self._json(response, "login")
            info = login_data.get("token_info")
            if not isinstance(info, dict) or not info.get("login_token") or not info.get("user_id"):
                raise UpstreamError("LOGIN_RESPONSE", "login", status=response.status_code,
                                    business_code=login_data.get("error_code", login_data.get("code")))
            login_token, user_id = str(info["login_token"]), str(info["user_id"])
            response = self._request(session, "GET", APP_TOKEN_URL, "appToken", params={
                "app_name": APP_NAME, "dn": DN, "login_token": login_token,
            }, headers=client_headers())
            app_data = self._json(response, "appToken")
            info = app_data.get("token_info")
            if not isinstance(info, dict) or not info.get("app_token"):
                raise UpstreamError("LOGIN_RESPONSE", "appToken", status=response.status_code,
                                    business_code=app_data.get("error_code", app_data.get("code")))
            return Auth(user_id=user_id, app_token=str(info["app_token"]), device_id=secrets.token_hex(8).upper(),
                        data_host=select_data_host(app_data, login_data))

    def upload(self, auth: Auth, record: list[dict]) -> dict:
        # No automatic retry: a lost response does not prove the write failed.
        with self._session() as session:
            response = self._request(session, "POST", "https://" + auth.data_host + "/v1/data/band_data.json", "upload",
                params={"t": str(int(time.time() * 1000))},
                data={
                    "userid": auth.user_id, "last_sync_data_time": str(int(time.time())),
                    "device_type": "0", "last_deviceid": auth.device_id,
                    "data_json": json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                }, headers={
                    **client_headers(),
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Accept-Encoding": "gzip, deflate", "apptoken": auth.app_token,
                })
            data = self._json(response, "upload")
            code = data.get("code")
            if type(code) is not int or code != 1:
                raise UpstreamError("UPLOAD_REJECTED", "upload", status=response.status_code,
                                    business_code=data.get("error_code", data.get("code")))
            # Never forward raw upstream JSON: it can contain credentials or PII.
            return {"accepted": True, "upstreamHttpStatus": response.status_code,
                    "upstreamCode": 1, "effectVerified": False, "dataHost": auth.data_host}


    def read_steps(self, auth: Auth, date: str) -> dict:
        """Read only today's summary from the SAME data region used for upload."""
        with self._session() as session:
            response = self._request(session, "GET", "https://" + auth.data_host + "/v1/data/band_data.json", "verify",
                params={"query_type": "summary", "device_type": "android_phone", "userid": auth.user_id,
                        "from_date": date, "to_date": date, "t": str(int(time.time() * 1000))},
                headers={**client_headers(), "apptoken": auth.app_token})
            data = self._json(response, "verify")
            if type(data.get("code")) is not int or data.get("code") != 1:
                raise UpstreamError("VERIFY_REJECTED", "verify", status=response.status_code,
                                    business_code=data.get("error_code", data.get("code")))
            values = parse_step_values(data, date)
            return {"ok": True, "date": date, "steps": values,
                    "dataHost": auth.data_host, "upstreamHttpStatus": response.status_code}
