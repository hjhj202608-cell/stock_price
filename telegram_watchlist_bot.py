from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

import requests

WATCHLIST_PATH = Path("watchlist.json")
STATE_PATH = Path(".telegram_bot_state.json")
MAX_SECURITIES = 10
NAVER_SECURITY_SEARCH_URL = "https://ac.stock.naver.com/ac"
SecuritySearch = Callable[[str], list[dict[str, str]]]


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
        "• 추가 삼성전자\n"
        "• 삭제 삼성전자\n"
        "• 목록\n\n"
        "종목명만 보내면 코드를 확인해 처리합니다. 다음 종가 알림부터 반영됩니다."
    )


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def search_securities_by_name(
    session: requests.Session, query: str
) -> list[dict[str, str]]:
    response = session.get(
        NAVER_SECURITY_SEARCH_URL,
        params={"q": query, "target": "stock"},
        headers={"User-Agent": "stock-price-telegram-bot/1.0"},
        timeout=15,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    payload = response.json()
    candidates: list[dict[str, str]] = []
    for item in payload.get("items") or []:
        code = str(item.get("code", "")).strip().upper()
        name = str(item.get("name", "")).strip()
        if (
            item.get("nationCode") == "KOR"
            and item.get("category") == "stock"
            and re.fullmatch(r"[0-9A-Z]{6}", code)
            and name
        ):
            candidates.append({"code": code, "name": name})
    return candidates


def _candidate_reply(query: str, candidates: list[dict[str, str]]) -> str:
    if not candidates:
        return f"국내 상장 종목을 찾지 못했습니다: {query}"
    lines = [f"정확히 일치하는 종목이 없습니다: {query}", "아래 이름 중 하나를 그대로 보내 주세요."]
    lines.extend(f"• 추가 {item['name']}" for item in candidates[:5])
    return "\n".join(lines)


def process_command(
    text: str,
    watchlist: list[dict[str, str]],
    security_search: SecuritySearch | None = None,
) -> tuple[str, bool]:
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
        if len(parts) < 2:
            return "형식: 추가 삼성전자", False
        first_argument = parts[1].upper()
        if re.fullmatch(r"[0-9A-Z]{6}", first_argument) and len(parts) >= 3:
            code, name = first_argument, parts[2].strip()
        else:
            query = " ".join(parts[1:]).strip()
            if security_search is None:
                return "종목 이름 검색을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.", False
            try:
                candidates = security_search(query)
            except (requests.RequestException, ValueError, TypeError):
                return "종목 검색이 잠시 원활하지 않습니다. 잠시 후 다시 시도해 주세요.", False
            exact = [
                item
                for item in candidates
                if _normalized_name(item["name"]) == _normalized_name(query)
            ]
            if len(exact) != 1:
                return _candidate_reply(query, exact or candidates), False
            code, name = exact[0]["code"], exact[0]["name"]
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
            return "형식: 삭제 삼성전자", False
        query = " ".join(parts[1:]).strip()
        if re.fullmatch(r"[0-9A-Z]{6}", query.upper()):
            matches = [item for item in watchlist if item["code"] == query.upper()]
        else:
            matches = [
                item
                for item in watchlist
                if _normalized_name(item["name"]) == _normalized_name(query)
            ]
        if len(matches) > 1:
            lines = ["같은 이름의 종목이 여러 개입니다. 종목코드로 삭제해 주세요."]
            lines.extend(f"• 삭제 {item['code']} ({item['name']})" for item in matches)
            return "\n".join(lines), False
        existing = matches[0] if matches else None
        if not existing:
            return f"등록되지 않은 종목입니다: {query}", False
        watchlist.remove(existing)
        return f"삭제했습니다: {existing['name']} ({existing['code']})", True

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
        reply, changed = process_command(
            text,
            watchlist,
            security_search=lambda query: search_securities_by_name(session, query),
        )
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
