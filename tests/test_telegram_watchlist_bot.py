import telegram_watchlist_bot as bot


def test_add_list_and_remove_commands():
    watchlist = []

    reply, changed = bot.process_command("추가 005930 삼성전자", watchlist)
    assert changed
    assert "추가했습니다" in reply
    assert watchlist == [{"code": "005930", "name": "삼성전자"}]

    reply, changed = bot.process_command("목록", watchlist)
    assert not changed
    assert "삼성전자 (005930)" in reply

    reply, changed = bot.process_command("삭제 005930", watchlist)
    assert changed
    assert "삭제했습니다" in reply
    assert watchlist == []


def test_rejects_invalid_code_and_duplicate():
    watchlist = [{"code": "005930", "name": "삼성전자"}]
    reply, changed = bot.process_command("추가 5930 삼성전자", watchlist)
    assert not changed
    assert "6자리" in reply

    reply, changed = bot.process_command("추가 005930 삼성전자", watchlist)
    assert not changed
    assert "이미 등록" in reply
