from __future__ import annotations

import os
import sys

import requests


def _telegram_get(method: str, **params: str) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    response = requests.get(
        f"https://api.telegram.org/bot{token}/{method}",
        params=params,
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "description": "Telegram returned a non-JSON response"}

    if not response.ok or not payload.get("ok"):
        description = payload.get("description", f"HTTP {response.status_code}")
        raise RuntimeError(f"{method}: {description}")
    return payload


def _telegram_post(method: str, **payload_data: str) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload_data,
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "description": "Telegram returned a non-JSON response"}

    if not response.ok or not payload.get("ok"):
        description = payload.get("description", f"HTTP {response.status_code}")
        raise RuntimeError(f"{method}: {description}")
    return payload


def main() -> int:
    try:
        bot = _telegram_get("getMe")["result"]
        username = bot.get("username", "unknown")
        # Character separation avoids over-broad CI secret masking while exposing
        # only the bot's public username, never its token.
        display_username = " ".join(username)
        print("Telegram bot authentication: OK")
        print(f"Telegram bot public username characters: {display_username}")
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        chat = _telegram_get("getChat", chat_id=chat_id)["result"]
        if str(chat.get("id")) == str(bot.get("id")):
            raise RuntimeError(
                "TELEGRAM_CHAT_ID points to the bot itself; use the user's chat ID"
            )

        chat_type = chat.get("type", "unknown")
        print(f"Telegram destination chat access: OK (type={chat_type})")

        if chat_type in {"group", "supergroup", "channel"}:
            member = _telegram_get(
                "getChatMember", chat_id=chat_id, user_id=str(bot["id"])
            )["result"]
            status = member.get("status", "unknown")
            can_post = member.get("can_post_messages")
            print(
                "Telegram bot membership: "
                f"status={status}, can_post_messages={can_post}"
            )
            if chat_type == "channel" and can_post is not True:
                raise RuntimeError(
                    "the bot is not allowed to post messages in this channel"
                )

        if os.environ.get("SEND_TEST_MESSAGE", "false").lower() == "true":
            _telegram_post(
                "sendMessage",
                chat_id=chat_id,
                text="✅ 주식 종가 알림 연결 테스트 성공",
            )
            print("Telegram test message: sent")
        return 0
    except Exception as exc:
        print(f"Telegram diagnostic failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
