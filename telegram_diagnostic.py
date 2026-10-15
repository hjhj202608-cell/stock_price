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


def main() -> int:
    try:
        bot = _telegram_get("getMe")["result"]
        print(f"Telegram bot authentication: OK (@{bot.get('username', 'unknown')})")
        _telegram_get("getChat", chat_id=os.environ["TELEGRAM_CHAT_ID"])
        print("Telegram destination chat access: OK")
        return 0
    except Exception as exc:
        print(f"Telegram diagnostic failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
