from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import requests

KST = ZoneInfo("Asia/Seoul")
KIWOOM_BASE_URL = "https://api.kiwoom.com"
TOKEN_PATH = "/oauth2/token"
CHART_PATH = "/api/dostk/chart"
TARGET_TIME = time(15, 30)
RUN_NOT_BEFORE = time(15, 35)


@dataclass(frozen=True)
class Security:
    code: str
    name: str


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


def issue_token(session: requests.Session) -> str:
    response = session.post(
        f"{KIWOOM_BASE_URL}{TOKEN_PATH}",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={
            "grant_type": "client_credentials",
            "appkey": os.environ["KIWOOM_APP_KEY"],
            "secretkey": os.environ["KIWOOM_APP_SECRET"],
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("return_code") not in (None, 0, "0"):
        raise RuntimeError(payload.get("return_msg", "키움 토큰 발급 실패"))
    token = payload.get("token")
    if not token:
        raise RuntimeError("키움 응답에 접근 토큰이 없습니다")
    return str(token)


def _normalize_price(value: Any) -> int:
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError("빈 가격")
    return abs(int(float(text)))


def _parse_execution_time(value: Any, today: str) -> datetime | None:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    candidates = []
    if len(digits) >= 14:
        candidates.append(digits[:14])
    if len(digits) >= 6:
        candidates.append(today + digits[-6:])
    for candidate in candidates:
        try:
            return datetime.strptime(candidate, "%Y%m%d%H%M%S").replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def fetch_1530_close(
    session: requests.Session, token: str, security: Security, now: datetime
) -> int:
    response = session.post(
        f"{KIWOOM_BASE_URL}{CHART_PATH}",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": "ka10080",
        },
        json={
            "stk_cd": security.code,
            "tic_scope": "1",
            "upd_stkpc_tp": "1",
            "base_dt": now.strftime("%Y%m%d"),
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("return_code") not in (None, 0, "0"):
        raise RuntimeError(payload.get("return_msg", "키움 시세 조회 실패"))

    rows = payload.get("stk_min_pole_chart_qry") or []
    for row in rows:
        stamp = _parse_execution_time(row.get("cntr_tm"), now.strftime("%Y%m%d"))
        if stamp and stamp.date() == now.date() and stamp.time() == TARGET_TIME:
            return _normalize_price(row.get("cur_prc"))
    raise LookupError("당일 15:30 KRX 분봉을 찾지 못했습니다")


def build_message(now: datetime, prices: dict[str, int | None]) -> str:
    lines = [f"[KRX 종가] {now:%Y-%m-%d} 15:30"]
    for security in SECURITIES:
        price = prices.get(security.code)
        rendered = f"{price:,}원" if price is not None else "확인불가"
        lines.append(f"• {security.name} ({security.code}): {rendered}")
    return "\n".join(lines)


def send_telegram(session: requests.Session, message: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    response = session.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))


def main(now: datetime | None = None) -> int:
    now = (now or datetime.now(KST)).astimezone(KST)
    if now.time() < RUN_NOT_BEFORE:
        logging.info("15:35 KST 이전이므로 전송하지 않습니다: %s", now.isoformat())
        return 0
    if not is_krx_session(now):
        logging.info("KRX 휴장일이므로 전송하지 않습니다: %s", now.date())
        return 0

    session = requests.Session()
    prices: dict[str, int | None] = {item.code: None for item in SECURITIES}
    try:
        token = issue_token(session)
    except Exception:
        logging.exception("키움 인증 실패; 모든 종목을 확인불가로 전송합니다")
    else:
        for security in SECURITIES:
            try:
                prices[security.code] = fetch_1530_close(session, token, security, now)
            except Exception:
                logging.exception("%s(%s) 종가 조회 실패", security.name, security.code)

    message = build_message(now, prices)
    send_telegram(session, message)
    logging.info("텔레그램 전송 완료\n%s", message)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        sys.exit(main())
    except Exception:
        logging.exception("알림 작업 실패")
        sys.exit(1)
