from datetime import datetime
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


def test_parse_execution_time_supports_full_timestamp():
    stamp = app._parse_execution_time("20261015153000", "20261015")
    assert stamp == datetime(2026, 10, 15, 15, 30, tzinfo=KST)


def test_price_normalization_removes_api_sign():
    assert app._normalize_price("-12,345") == 12_345


def test_krx_session_gate():
    assert app.is_krx_session(datetime(2026, 10, 15, 15, 35, tzinfo=KST))
    assert not app.is_krx_session(datetime(2026, 10, 3, 15, 35, tzinfo=KST))
