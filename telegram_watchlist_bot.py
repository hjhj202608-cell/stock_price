from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import requests

WATCHLIST_PATH = Path("watchlist.json")
STATE_PATH = Path(".telegram_bot_state.json")
MAX_SECURITIES = 10


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def help_message() -> str:
    return (
        "종가 알림 종목 관리 방법\n"
        "• 추가 005930 삼성전자\n"
        "• 삭제 005930\n"
        "• 목록\n\n"
        "종목코드와 종목명을 함께 보내 주세요. 다음 종가 알림부터 반영됩니다."
    )


def process_command(text: str, watchlist: list[dict[str, str]]) -> tuple[str, bool]:
    text = re.sub(r"^/", "", text.strip())
    parts = text.split(maxsplit=2)
    if not parts:
        return help_message(), False
    command = parts[0].split("@")[0].lower()

    if command in {"목록", "list"}:
        if not watchlist:
            return "현재 등록된 종목이 없습니다.", False
        lines = ["현재 종가 알림 종목"]
        lines.extend(f"• {item['name']} ({item['code']})" for item in watchlist)
        return "\n".join(lines), False

    if command in {"도움말", "도움", "help", "start"}:
        return help_message(), False

    if command in {"추가", "add"}:
        if len(parts) < 3:
            return "형식: 추가 005930 삼성전자", False
        code, name = parts[1].upper(), parts[2].strip()
        if not re.fullmatch(r"[0-9A-Z]{6}", code) or not name:
            return "종목코드는 영문·숫자 6자리로 입력해 주세요.", False
        existing = next((item for item in watchlist if item["code"] == code), None)
        if existing:
            if existing["name"] == name:
                return f"이미 등록된 종목입니다: {name} ({code})", False
            existing["name"] = name
            return f"종목명을 변경했습니다: {name} ({code})", True
        if len(watchlist) >= MAX_SECURITIES:
            return f"종목은 최대 {MAX_SECURITIES}개까지 등록할 수 있습니다.", False
        watchlist.append({"code": code, "name": name})
        return f"추가했습니다: {name} ({code})", True

    if command in {"삭제", "제거", "remove", "delete"}:
        if len(parts) < 2:
            return "형식: 삭제 005930", False
        code = parts[1].upper()
        existing = next((item for item in watchlist if item["code"] == code), None)
        if not existing:
            return f"등록되지 않은 종목입니다: {code}", False
        watchlist.remove(existing)
        return f"삭제했습니다: {existing['name']} ({code})", True

    return help_message(), False


def telegram_call(session: requests.Session, method: str, **payload: Any) -> Any:
    response = session.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}",
        json=payload,
        timeout=20,
    )
    data = response.json()
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("description", f"HTTP {response.status_code}"))
    return data.get("result")


def commit_changes() -> None:
    subprocess.run(["git", "config", "user.name", "stock-price-bot"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "stock-price-bot@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(
        ["git", "add", str(WATCHLIST_PATH), str(STATE_PATH)], check=True
    )
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", "Update Telegram bot watchlist"], check=True)
    subprocess.run(["git", "push"], check=True)


def main() -> int:
    session = requests.Session()
    watchlist = load_json(WATCHLIST_PATH, [])
    state = load_json(STATE_PATH, {"last_update_id": 0})
    offset = int(state.get("last_update_id", 0)) + 1
    updates = telegram_call(session, "getUpdates", offset=offset, timeout=0) or []
    authorized_chat = str(os.environ["TELEGRAM_CHAT_ID"])
    watchlist_changed = False

    for update in updates:
        update_id = int(update["update_id"])
        state["last_update_id"] = max(int(state.get("last_update_id", 0)), update_id)
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = message.get("text")
        if chat_id != authorized_chat or not isinstance(text, str):
            continue
        reply, changed = process_command(text, watchlist)
        if changed:
            save_json(WATCHLIST_PATH, watchlist)
            watchlist_changed = True
        telegram_call(session, "sendMessage", chat_id=authorized_chat, text=reply)

    if updates:
        save_json(STATE_PATH, state)
        if not watchlist_changed and not WATCHLIST_PATH.exists():
            save_json(WATCHLIST_PATH, watchlist)
        commit_changes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
