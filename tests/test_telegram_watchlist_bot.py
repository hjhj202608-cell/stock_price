import telegram_watchlist_bot as bot


def fake_search(query: str):
    items = [
        {"code": "005930", "name": "삼성전자"},
        {"code": "448330", "name": "KODEX 삼성전자채권혼합"},
    ]
    return [item for item in items if query.replace(" ", "") in item["name"].replace(" ", "")]


def test_add_list_and_remove_commands():
    watchlist = []

    reply, changed = bot.process_command("추가 삼성전자", watchlist, fake_search)
    assert changed
    assert "추가했습니다" in reply
    assert watchlist == [{"code": "005930", "name": "삼성전자"}]

    reply, changed = bot.process_command("목록", watchlist)
    assert not changed
    assert "삼성전자 (005930)" in reply

    reply, changed = bot.process_command("삭제 삼성전자", watchlist)
    assert changed
    assert "삭제했습니다" in reply
    assert watchlist == []


def test_rejects_invalid_code_and_duplicate():
    watchlist = [{"code": "005930", "name": "삼성전자"}]
    reply, changed = bot.process_command("추가 없는종목", watchlist, fake_search)
    assert not changed
    assert "찾지 못했습니다" in reply

    reply, changed = bot.process_command("추가 005930 삼성전자", watchlist)
    assert not changed
    assert "이미 등록" in reply


def test_name_add_requires_exact_match_and_suggests_candidates():
    watchlist = []
    reply, changed = bot.process_command("추가 삼성", watchlist, fake_search)
    assert not changed
    assert "정확히 일치" in reply
    assert "추가 삼성전자" in reply
    assert watchlist == []


def test_name_delete_handles_spaces_and_keeps_code_compatibility():
    watchlist = [{"code": "123456", "name": "테스트 종목"}]
    reply, changed = bot.process_command("삭제 테스트종목", watchlist)
    assert changed
    assert "삭제했습니다" in reply
    assert watchlist == []

    watchlist.append({"code": "005930", "name": "삼성전자"})
    reply, changed = bot.process_command("삭제 005930", watchlist)
    assert changed
    assert watchlist == []


def test_search_filters_non_korean_and_invalid_results(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {"code": "005930", "name": "삼성전자", "nationCode": "KOR", "category": "stock"},
                    {"code": "AAPL", "name": "Apple", "nationCode": "USA", "category": "stock"},
                    {"code": "123", "name": "잘못된코드", "nationCode": "KOR", "category": "stock"},
                ]
            }

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    assert bot.search_securities_by_name(Session(), "삼성전자") == [
        {"code": "005930", "name": "삼성전자"}
    ]
