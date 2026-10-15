from __future__ import annotations

import os
import sys
import time

import requests


def discover_private_start_chat(
    token: str, *, now: int | None = None, max_age_seconds: int = 86_400
) -> str:
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"limit": 100, "allowed_updates": '["message"]'},
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Telegram returned a non-JSON response") from exc

    if not response.ok or not payload.get("ok"):
        description = payload.get("description", f"HTTP {response.status_code}")
        raise RuntimeError(f"getUpdates: {description}")

    cutoff = (now if now is not None else int(time.time())) - max_age_seconds
    candidates: dict[str, int] = {}
    for update in payload.get("result", []):
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        text = str(message.get("text", "")).strip()
        sent_at = int(message.get("date", 0))
        if (
            chat.get("type") == "private"
            and text.split(maxsplit=1)[0] == "/start"
            and sent_at >= cutoff
        ):
            candidates[str(chat["id"])] = sent_at

    if not candidates:
        raise RuntimeError("No recent private /start message was found")
    if len(candidates) != 1:
        raise RuntimeError(
            "More than one recent private /start chat was found; refusing to guess"
        )
    return next(iter(candidates))


def main() -> int:
    try:
        print(discover_private_start_chat(os.environ["TELEGRAM_BOT_TOKEN"]))
        return 0
    except Exception as exc:
        print(f"Telegram chat discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
