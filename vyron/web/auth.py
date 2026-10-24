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
OWNER_TOKEN_PREFIX = "vown_"
OWNER_TOKEN_TTL = 30 * 86400  # long enough for scripts, short enough to rotate


@dataclass
class WebUser:
    user_id: int = 0
    name: str = ""
    username: str = ""
    chat_id: int = 0
    source: str = "anon"
    auth_date: int = 0
    owner: bool = False
    epoch: int = 0

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


def make_owner_token(
    bot_token: str,
    owner_id: int,
    *,
    ttl: int = OWNER_TOKEN_TTL,
    epoch: int = 0,
) -> str:
    """A bearer token that grants owner access to the web app *and* the API.

    Signed with the bot token, so rotating ``BOT_TOKEN`` revokes every token;
    ``epoch`` adds per-owner revocation on top of that (see `core.tokens`).
    """
    if not bot_token or not owner_id:
        return ""
    expires = int(time.time()) + max(0, int(ttl))
    payload = f"{int(owner_id)}:{expires}:{int(epoch or 0)}"
    blob = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(bot_token.encode(), f"owner:{blob}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{OWNER_TOKEN_PREFIX}{blob}.{signature}"


def owner_token_epoch(token: str, bot_token: str) -> int | None:
    """The epoch a *valid* token was minted in (``None`` when invalid)."""
    who = verify_owner_token(token, bot_token)
    if who is None:
        return None
    return int(getattr(who, "epoch", 0) or 0)


def verify_owner_token(
    token: str,
    bot_token: str,
    *,
    expected_epoch: int | None = None,
) -> WebUser | None:
    """Validate an owner token; returns a `WebUser` with ``owner=True``.

    ``expected_epoch`` rejects tokens issued before a revocation.
    """
    token = (token or "").strip()
    if not token.startswith(OWNER_TOKEN_PREFIX) or "." not in token or not bot_token:
        return None
    blob, _, signature = token[len(OWNER_TOKEN_PREFIX):].partition(".")
    expected = hmac.new(bot_token.encode(), f"owner:{blob}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        padded = blob + "=" * (-len(blob) % 4)
        parts = base64.urlsafe_b64decode(padded).decode().split(":")
        owner_id, expires = parts[0], parts[1]
        token_epoch = int(parts[2]) if len(parts) > 2 else 0
        owner_id_int, expires_int = int(owner_id), int(expires)
    except Exception:
        return None
    if expires_int and expires_int < time.time():
        return None
    if expected_epoch is not None and token_epoch != int(expected_epoch):
        return None
    return WebUser(
        user_id=owner_id_int,
        name="Owner",
        source="owner",
        owner=True,
        epoch=token_epoch,
    )


def resolve_user(
    *,
    init_data: str,
    token: str,
    bot_token: str,
    allow_anon: bool = False,
    owner_ids: set[int] | frozenset[int] | None = None,
    owner_epoch: int | None = None,
) -> WebUser:
    """Pick the best available identity, preferring signed chat tokens."""
    owner = (
        verify_owner_token(token, bot_token, expected_epoch=owner_epoch) if token else None
    )
    if owner is not None and (not owner_ids or owner.user_id in owner_ids):
        return owner

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


__all__ = [
    "OWNER_TOKEN_PREFIX",
    "OWNER_TOKEN_TTL",
    "WebUser",
    "make_owner_token",
    "owner_token_epoch",
    "make_token",
    "resolve_user",
    "verify_init_data",
    "verify_owner_token",
    "verify_token",
]
