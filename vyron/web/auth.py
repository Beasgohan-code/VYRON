# ---------------------------------------------------------------------------
#  VYRON — web app authentication
#
#  Two supported flows:
#    · Telegram initData  — HMAC-SHA256(secret=HMAC("WebAppData", token))
#    · Signed chat token  — so the Mini App can control a *group* player when it
#      was opened from that group (initData only carries the user).
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

TOKEN_TTL = 12 * 3600


@dataclass
class WebUser:
    user_id: int = 0
    name: str = ""
    username: str = ""
    chat_id: int = 0
    source: str = "anon"
    auth_date: int = 0

    @property
    def authenticated(self) -> bool:
        return bool(self.user_id)


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(init_data: str, bot_token: str, *, max_age: int = 86400) -> WebUser | None:
    """Validate Telegram.WebApp.initData. Returns None when invalid."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=False))
    except Exception:
        return None
    received = pairs.pop("hash", "")
    if not received:
        return None
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    expected = hmac.new(_secret(bot_token), check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        auth_date = int(pairs.get("auth_date", "0") or 0)
    except ValueError:
        auth_date = 0
    if max_age and auth_date and time.time() - auth_date > max_age:
        return None

    user: WebUser = WebUser(auth_date=auth_date, source="initdata")
    raw_user = pairs.get("user")
    if raw_user:
        try:
            payload = json.loads(raw_user)
            user.user_id = int(payload.get("id") or 0)
            user.name = " ".join(
                filter(None, [payload.get("first_name"), payload.get("last_name")])
            ).strip()
            user.username = str(payload.get("username") or "")
        except Exception:
            pass

    raw_chat = pairs.get("chat")
    if raw_chat:
        try:
            user.chat_id = int(json.loads(raw_chat).get("id") or 0)
        except Exception:
            pass
    return user if user.authenticated else None


def _sign(payload: str, bot_token: str) -> str:
    return hmac.new(bot_token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(chat_id: int, user_id: int, bot_token: str, *, ttl: int = TOKEN_TTL) -> str:
    """Compact, signed ``<b64 payload>.<sig>`` token for a chat context."""
    payload = json.dumps(
        {"c": int(chat_id), "u": int(user_id), "e": int(time.time()) + ttl},
        separators=(",", ":"),
    )
    blob = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{blob}.{_sign(blob, bot_token)}"


def verify_token(token: str, bot_token: str) -> WebUser | None:
    if not token or "." not in token or not bot_token:
        return None
    blob, _, signature = token.partition(".")
    if not hmac.compare_digest(_sign(blob, bot_token), signature):
        return None
    try:
        padded = blob + "=" * (-len(blob) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None
    if int(payload.get("e", 0)) < time.time():
        return None
    return WebUser(
        user_id=int(payload.get("u") or 0),
        chat_id=int(payload.get("c") or 0),
        source="token",
    )


def resolve_user(
    *,
    init_data: str,
    token: str,
    bot_token: str,
    allow_anon: bool = False,
) -> WebUser:
    """Pick the best available identity, preferring signed chat tokens."""
    signed = verify_token(token, bot_token) if token else None
    telegram = verify_init_data(init_data, bot_token) if init_data else None

    if signed and telegram:
        signed.name, signed.username = telegram.name, telegram.username
        signed.user_id = signed.user_id or telegram.user_id
        return signed
    if signed:
        return signed
    if telegram:
        if not telegram.chat_id:
            telegram.chat_id = telegram.user_id  # private chat with the bot
        return telegram
    if allow_anon:
        return WebUser(source="anon")
    return WebUser()


__all__ = ["WebUser", "make_token", "resolve_user", "verify_init_data", "verify_token"]
