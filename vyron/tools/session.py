#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — assistant session generator
#
#  The assistant (userbot) account is what actually joins voice chats, so it
#  needs a STRING_SESSION.  This walks you through producing one:
#
#      python -m vyron.tools.session
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import os

from pyrogram import Client

from vyron.config import settings


async def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = await asyncio.to_thread(input, f"{label}{suffix}: ")
    return value.strip() or default


async def main() -> None:
    print("VYRON · assistant session generator")
    print("─" * 44)
    api_id = int(await _prompt("API_ID", str(settings.api_id or "")))
    api_hash = await _prompt("API_HASH", settings.api_hash)
    phone = await _prompt("Phone number (+countrycode…)")

    client = Client(
        name="vyron_session_gen",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
        device_model="VYRON Assistant",
    )
    await client.connect()

    try:
        sent = await client.send_code(phone)
        code = await _prompt("Login code")
        try:
            await client.sign_in(phone, sent.phone_code_hash, code)
        except Exception:
            password = await _prompt("2FA password")
            await client.check_password(password)

        me = await client.get_me()
        session_string = await client.export_session_string()
    finally:
        await client.disconnect()

    print("\n" + "═" * 60)
    print(f"Signed in as {me.first_name} (@{me.username or 'no username'})")
    print("Add this line to your .env:\n")
    print(f"STRING_SESSION={session_string}\n")
    print("⚠  Treat this like a password — it grants full account access.")
    print("═" * 60)

    if os.getenv("VYRON_WRITE_ENV") == "1":
        with open(".env", "a", encoding="utf-8") as handle:
            handle.write(f"\nSTRING_SESSION={session_string}\n")
        print("✔ appended to .env")


if __name__ == "__main__":
    asyncio.run(main())
