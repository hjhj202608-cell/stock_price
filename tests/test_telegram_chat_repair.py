import telegram_chat_repair as repair


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_discovers_one_recent_private_start(monkeypatch):
    monkeypatch.setattr(
        repair.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "ok": True,
                "result": [
                    {
                        "message": {
                            "date": 999_900,
                            "text": "/start",
                            "chat": {"id": 1234, "type": "private"},
                        }
                    },
                    {
                        "message": {
                            "date": 999_950,
                            "text": "hello",
                            "chat": {"id": 9999, "type": "private"},
                        }
                    },
                ],
            }
        ),
    )

    assert repair.discover_private_start_chat("token", now=1_000_000) == "1234"


def test_refuses_to_guess_between_two_recent_private_starts(monkeypatch):
    monkeypatch.setattr(
        repair.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "ok": True,
                "result": [
                    {
                        "message": {
                            "date": 999_900,
                            "text": "/start",
                            "chat": {"id": 1234, "type": "private"},
                        }
                    },
                    {
                        "message": {
                            "date": 999_950,
                            "text": "/start payload",
                            "chat": {"id": 5678, "type": "private"},
                        }
                    },
                ],
            }
        ),
    )

    try:
        repair.discover_private_start_chat("token", now=1_000_000)
    except RuntimeError as exc:
        assert "refusing to guess" in str(exc)
    else:
        raise AssertionError("여러 대화가 있으면 자동 선택하면 안 됩니다")
