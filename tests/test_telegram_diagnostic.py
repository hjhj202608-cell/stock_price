import telegram_diagnostic as diagnostic


class FakeResponse:
    def __init__(self, payload: dict, ok: bool = True, status_code: int = 200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_diagnostic_checks_bot_and_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    responses = iter(
        [
            FakeResponse({"ok": True, "result": {"username": "test_bot"}}),
            FakeResponse({"ok": True, "result": {"id": 1234}}),
        ]
    )
    monkeypatch.setattr(diagnostic.requests, "get", lambda *args, **kwargs: next(responses))

    assert diagnostic.main() == 0


def test_diagnostic_reports_telegram_description(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setattr(
        diagnostic.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {"ok": False, "description": "Forbidden: bot was blocked by the user"},
            ok=False,
            status_code=403,
        ),
    )

    assert diagnostic.main() == 1
    assert "bot was blocked by the user" in capsys.readouterr().err
