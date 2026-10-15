from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import sys
import time as time_module
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import requests

KST = ZoneInfo("Asia/Seoul")
CRON_API_URL = "https://api.cron-job.org"
CRON_NODES_URL = f"{CRON_API_URL}/executor-nodes.json"
KIWOOM_BASE_URL = "https://api.kiwoom.com"
RUN_NOT_BEFORE = time(15, 35)
EXPECTED_CRON_IPS = {
    "116.203.134.67",
    "116.203.129.16",
    "23.88.105.37",
    "128.140.8.200",
    "91.99.23.109",
}


@dataclass(frozen=True)
class Security:
    code: str
    name: str


@dataclass(frozen=True)
class RelayResult:
    http_status: int
    body: str


SECURITIES = (
    Security("0048J0", "KODEX 미국머니마켓액티브"),
    Security("0046A0", "TIGER 미국초단기(3개월이하)국채"),
    Security("329750", "TIGER 미국달러단기채권액티브"),
)


def is_krx_session(now: datetime) -> bool:
    calendar = xcals.get_calendar(
        "XKRX", start=f"{now.year}-01-01", end=f"{now.year}-12-31"
    )
    return calendar.is_session(now.date())


def _normalize_price(value: Any) -> int:
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError("빈 가격")
    return abs(int(float(text)))


def _extract_ipv4s(value: Any) -> set[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(key)
                visit(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            for candidate in re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", item):
                try:
                    found.add(str(ipaddress.ip_address(candidate)))
                except ValueError:
                    continue

    visit(value)
    return found


def verify_cron_executor_ips(session: requests.Session) -> set[str]:
    response = session.get(CRON_NODES_URL, timeout=15)
    response.raise_for_status()
    current = _extract_ipv4s(response.json())
    if not current:
        raise RuntimeError("cron-job.org 실행 IP 목록을 읽지 못했습니다")
    unexpected = current - EXPECTED_CRON_IPS
    if unexpected:
        raise RuntimeError(
            "키움 허용 목록에 없는 cron-job.org IP: " + ", ".join(sorted(unexpected))
        )
    return current


class CronJobClient:
    def __init__(self, session: requests.Session, api_key: str) -> None:
        self.session = session
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _post_job_payload(
        *,
        title: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        run_at: datetime,
    ) -> dict[str, Any]:
        run_at = run_at.astimezone(timezone.utc).replace(second=0, microsecond=0)
        expires_at = run_at + timedelta(minutes=5)
        return {
            "job": {
                "title": title[:128],
                "url": url,
                "enabled": True,
                "saveResponses": True,
                "requestMethod": 1,
                "requestTimeout": 30,
                "redirectSuccess": False,
                "schedule": {
                    "timezone": "UTC",
                    "expiresAt": int(expires_at.strftime("%Y%m%d%H%M%S")),
                    "hours": [run_at.hour],
                    "mdays": [run_at.day],
                    "minutes": [run_at.minute],
                    "months": [run_at.month],
                    "wdays": [-1],
                },
                "extendedData": {
                    "headers": headers,
                    "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                },
            }
        }

    def create_post_job(
        self,
        *,
        title: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        run_at: datetime,
    ) -> int:
        payload = self._post_job_payload(
            title=title, url=url, headers=headers, body=body, run_at=run_at
        )
        response = self.session.put(
            f"{CRON_API_URL}/jobs", headers=self.headers, json=payload, timeout=15
        )
        response.raise_for_status()
        job_id = response.json().get("jobId")
        if not job_id:
            raise RuntimeError("cron-job.org가 jobId를 반환하지 않았습니다")
        return int(job_id)

    def update_post_job(
        self,
        job_id: int,
        *,
        title: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        run_at: datetime,
    ) -> None:
        payload = self._post_job_payload(
            title=title, url=url, headers=headers, body=body, run_at=run_at
        )
        response = self.session.patch(
            f"{CRON_API_URL}/jobs/{job_id}",
            headers=self.headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    def wait_result(
        self, job_id: int, run_at: datetime, timeout_seconds: int = 120
    ) -> RelayResult:
        run_at = run_at.astimezone(timezone.utc)
        wait_seconds = max(
            0.0,
            (
                run_at + timedelta(seconds=8) - datetime.now(timezone.utc)
            ).total_seconds(),
        )
        if wait_seconds:
            time_module.sleep(wait_seconds)

        deadline = time_module.monotonic() + timeout_seconds
        while time_module.monotonic() < deadline:
            response = self.session.get(
                f"{CRON_API_URL}/jobs/{job_id}/history",
                headers=self.headers,
                timeout=15,
            )
            response.raise_for_status()
            history = response.json().get("history") or []
            eligible = [
                item
                for item in history
                if int(item.get("datePlanned") or 0) >= int(run_at.timestamp()) - 5
            ]
            if eligible:
                newest = max(eligible, key=lambda item: int(item.get("date") or 0))
                identifier = newest.get("identifier")
                if not identifier:
                    raise RuntimeError("cron-job.org 실행 식별자가 없습니다")
                detail = self.session.get(
                    f"{CRON_API_URL}/jobs/{job_id}/history/{identifier}",
                    headers=self.headers,
                    timeout=15,
                )
                detail.raise_for_status()
                item = detail.json().get("jobHistoryDetails") or {}
                return RelayResult(
                    http_status=int(item.get("httpStatus") or 0),
                    body=str(item.get("body") or ""),
                )
            time_module.sleep(5)
        raise TimeoutError("cron-job.org 임시 작업 결과 대기 시간 초과")

    def delete_job(self, job_id: int) -> None:
        response = self.session.delete(
            f"{CRON_API_URL}/jobs/{job_id}", headers=self.headers, timeout=15
        )
        response.raise_for_status()


def _next_relay_minute(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.replace(second=0, microsecond=0) + timedelta(minutes=2)


def issue_token_via_relay(cron: CronJobClient) -> tuple[str, int]:
    run_at = _next_relay_minute()
    job_id = cron.create_post_job(
        title=f"temporary-kiwoom-token-{uuid.uuid4().hex[:8]}",
        url=f"{KIWOOM_BASE_URL}/oauth2/token",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": "au10001",
        },
        body={
            "grant_type": "client_credentials",
            "appkey": os.environ["KIWOOM_APP_KEY"],
            "secretkey": os.environ["KIWOOM_APP_SECRET"],
        },
        run_at=run_at,
    )
    try:
        result = cron.wait_result(job_id, run_at)
        if result.http_status != 200:
            raise RuntimeError(f"키움 토큰 HTTP 오류: {result.http_status}")
        payload = json.loads(result.body)
        if payload.get("return_code") not in (None, 0, "0"):
            raise RuntimeError(payload.get("return_msg", "키움 토큰 발급 실패"))
        token = payload.get("token")
        if not token:
            raise RuntimeError("키움 응답에 접근 토큰이 없습니다")
        print(f"::add-mask::{token}")
        return str(token), job_id
    except Exception:
        try:
            cron.delete_job(job_id)
        except Exception:
            logging.exception("cron-job.org 임시 작업 삭제 실패: %s", job_id)
        raise


def _extract_today_close(payload: dict[str, Any], today: str) -> int:
    if payload.get("return_code") not in (None, 0, "0"):
        raise RuntimeError(payload.get("return_msg", "키움 종가 조회 실패"))
    rows = payload.get("daly_stkpc")
    if not isinstance(rows, list):
        raise LookupError("키움 응답에 일별주가 목록이 없습니다")
    row = next((item for item in rows if str(item.get("date", "")) == today), None)
    if row is None:
        raise LookupError("키움 응답에 오늘 날짜의 종가가 없습니다")
    return _normalize_price(row.get("close_pric"))


def fetch_close_prices_via_relay(
    cron: CronJobClient, job_id: int, token: str, now: datetime
) -> dict[str, int | None]:
    prices: dict[str, int | None] = {item.code: None for item in SECURITIES}
    for security in SECURITIES:
        try:
            run_at = _next_relay_minute()
            cron.update_post_job(
                job_id,
                title=f"temporary-kiwoom-close-{security.code}-{uuid.uuid4().hex[:6]}",
                url=f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "authorization": f"Bearer {token}",
                    "api-id": "ka10086",
                },
                body={
                    "stk_cd": security.code,
                    "qry_dt": now.strftime("%Y%m%d"),
                    "indc_tp": "0",
                },
                run_at=run_at,
            )
            result = cron.wait_result(job_id, run_at)
            if result.http_status != 200:
                raise RuntimeError(f"키움 시세 HTTP 오류: {result.http_status}")
            payload = json.loads(result.body)
            prices[security.code] = _extract_today_close(
                payload, now.strftime("%Y%m%d")
            )
        except Exception:
            logging.exception("%s(%s) 종가 조회 실패", security.name, security.code)
    return prices


def build_message(
    now: datetime, prices: dict[str, int | None], warning: str | None = None
) -> str:
    lines = [f"[KRX 종가] {now:%Y-%m-%d} 15:30"]
    for security in SECURITIES:
        price = prices.get(security.code)
        rendered = f"{price:,}원" if price is not None else "확인불가"
        lines.append(f"• {security.name} ({security.code}): {rendered}")
    if warning:
        lines.extend(("", f"⚠️ {warning}"))
    return "\n".join(lines)


def send_telegram(session: requests.Session, message: str) -> None:
    response = session.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message},
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "description": "Telegram returned a non-JSON response"}

    if not response.ok or not payload.get("ok"):
        description = payload.get("description", f"HTTP {response.status_code}")
        raise RuntimeError(f"텔레그램 전송 실패: {description}")


def requested_target_now(actual_now: datetime | None = None) -> datetime | None:
    raw = os.environ.get("TARGET_DATE", "").strip()
    if not raw:
        return None

    try:
        target_date = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("TARGET_DATE는 YYYY-MM-DD 형식이어야 합니다") from exc

    actual_now = (actual_now or datetime.now(KST)).astimezone(KST)
    if target_date > actual_now.date() or (
        target_date == actual_now.date() and actual_now.time() < RUN_NOT_BEFORE
    ):
        raise ValueError("아직 확정되지 않은 미래 종가는 발송할 수 없습니다")

    return datetime.combine(target_date, RUN_NOT_BEFORE, tzinfo=KST)


def main(now: datetime | None = None) -> int:
    now = (now or datetime.now(KST)).astimezone(KST)
    if now.time() < RUN_NOT_BEFORE:
        logging.info("15:35 KST 이전이므로 전송하지 않습니다: %s", now.isoformat())
        return 0
    if not is_krx_session(now):
        logging.info("KRX 휴장일이므로 전송하지 않습니다: %s", now.date())
        return 0

    session = requests.Session()
    empty = {item.code: None for item in SECURITIES}
    cron: CronJobClient | None = None
    relay_job_id: int | None = None
    try:
        verify_cron_executor_ips(session)
        cron = CronJobClient(session, os.environ["CRONJOB_API_KEY"])
        token, relay_job_id = issue_token_via_relay(cron)
        prices = fetch_close_prices_via_relay(cron, relay_job_id, token, now)
        message = build_message(now, prices)
    except Exception as exc:
        logging.exception("무료 중계 조회 실패")
        message = build_message(now, empty, str(exc))
    finally:
        if cron is not None and relay_job_id is not None:
            try:
                cron.delete_job(relay_job_id)
            except Exception:
                logging.exception("cron-job.org 임시 작업 삭제 실패: %s", relay_job_id)

    send_telegram(session, message)
    logging.info("텔레그램 전송 완료")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        sys.exit(main(requested_target_now()))
    except Exception:
        logging.exception("알림 작업 실패")
        sys.exit(1)
