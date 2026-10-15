from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import stock_close_alert as app


KST = ZoneInfo("Asia/Seoul")


def test_message_renders_price_and_unavailable():
    message = app.build_message(
        datetime(2026, 10, 15, 15, 35, tzinfo=KST),
        {"0048J0": 100_050, "0046A0": None, "329750": 12_345},
    )
    assert "100,050원" in message
    assert "0046A0): 확인불가" in message
    assert "12,345원" in message


def test_message_can_include_warning():
    message = app.build_message(
        datetime(2026, 10, 15, 15, 35, tzinfo=KST), {}, "IP 목록 변경"
    )
    assert "⚠️ IP 목록 변경" in message


def test_price_normalization_removes_api_sign():
    assert app._normalize_price("-12,345") == 12_345


def test_extract_today_close_uses_official_daily_list_shape():
    payload = {
        "daly_stkpc": [
            {"date": "20261014", "close_pric": "-10,000"},
            {"date": "20261015", "close_pric": "+12,345"},
        ],
        "return_code": 0,
    }
    assert app._extract_today_close(payload, "20261015") == 12_345


def test_extract_today_close_rejects_wrong_date():
    payload = {
        "daly_stkpc": [{"date": "20261014", "close_pric": "10,000"}],
        "return_code": 0,
    }
    try:
        app._extract_today_close(payload, "20261015")
    except LookupError:
        pass
    else:
        raise AssertionError("오늘 날짜가 없으면 가격을 인정하면 안 됩니다")


def test_fetch_prices_reuses_one_job_and_sends_required_fields(monkeypatch):
    class FakeCron:
        def __init__(self):
            self.bodies = []
            self.job_ids = []

        def update_post_job(self, job_id, **kwargs):
            self.job_ids.append(job_id)
            self.bodies.append(kwargs["body"])

        def wait_result(self, job_id, run_at):
            code = self.bodies[-1]["stk_cd"]
            return app.RelayResult(
                200,
                '{"daly_stkpc":[{"date":"20261015","close_pric":"%s"}],'
                '"return_code":0}' % {"0048J0": 101, "0046A0": 202, "329750": 303}[code],
            )

    monkeypatch.setattr(
        app,
        "_next_relay_minute",
        lambda: datetime(2026, 10, 15, 6, 37, tzinfo=timezone.utc),
    )
    cron = FakeCron()
    prices = app.fetch_close_prices_via_relay(
        cron, 777, "token", datetime(2026, 10, 15, 15, 35, tzinfo=KST)
    )

    assert cron.job_ids == [777, 777, 777]
    assert all(body["qry_dt"] == "20261015" for body in cron.bodies)
    assert all(body["indc_tp"] == "0" for body in cron.bodies)
    assert prices == {"0048J0": 101, "0046A0": 202, "329750": 303}


def test_extract_ipv4s_accepts_unknown_json_shape():
    payload = {"nodes": [{"address": "116.203.134.67"}, "91.99.23.109"]}
    assert app._extract_ipv4s(payload) == {"116.203.134.67", "91.99.23.109"}


def test_next_relay_minute_has_safe_lead_time():
    now = datetime(2026, 10, 15, 6, 35, 58, tzinfo=timezone.utc)
    assert app._next_relay_minute(now) == datetime(
        2026, 10, 15, 6, 37, tzinfo=timezone.utc
    )


def test_krx_session_gate():
    assert app.is_krx_session(datetime(2026, 10, 15, 15, 35, tzinfo=KST))
    assert not app.is_krx_session(datetime(2026, 10, 3, 15, 35, tzinfo=KST))


def test_send_telegram_reports_api_description(monkeypatch):
    class FakeResponse:
        ok = False
        status_code = 403

        @staticmethod
        def json():
            return {
                "ok": False,
                "description": "Forbidden: bot can't send messages to bots",
            }

    class FakeSession:
        @staticmethod
        def post(*args, **kwargs):
            return FakeResponse()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9999")

    try:
        app.send_telegram(FakeSession(), "test")
    except RuntimeError as exc:
        assert "bot can't send messages to bots" in str(exc)
    else:
        raise AssertionError("Telegram API 오류를 예외로 전달해야 합니다")


def test_requested_target_now_accepts_completed_historical_date(monkeypatch):
    monkeypatch.setenv("TARGET_DATE", "2026-10-15")
    actual = datetime(2026, 10, 16, 0, 5, tzinfo=KST)

    requested = app.requested_target_now(actual)

    assert requested == datetime(2026, 10, 15, 15, 35, tzinfo=KST)


def test_requested_target_now_rejects_today_before_close(monkeypatch):
    monkeypatch.setenv("TARGET_DATE", "2026-10-16")
    actual = datetime(2026, 10, 16, 9, 0, tzinfo=KST)

    try:
        app.requested_target_now(actual)
    except ValueError as exc:
        assert "미래 종가" in str(exc)
    else:
        raise AssertionError("장 마감 전 당일 종가는 허용하면 안 됩니다")
