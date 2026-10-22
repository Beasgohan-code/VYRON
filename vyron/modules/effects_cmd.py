# ---------------------------------------------------------------------------
#  VYRON — /effects (ffmpeg filters applied to the live stream)
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core import chatcfg, effects
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, is_chat_admin, is_owner


async def _active(chat_id: int) -> list[str]:
    return effects.resolve(await chatcfg.get(chat_id, "effects", []) or [])


def panel(active: list[str]) -> str:
    rows = []
    buttons: list[str] = []
    for name, effect in effects.EFFECTS.items():
        on = name in active
        rows.append((f"{'●' if on else '○'} <b>{effect.label}</b>", f"<i>{effect.note}</i>"))
        buttons.append(
            B.btn(
                f"{'●' if on else '○'} {effect.label}",
                data=f"v:fx:{name}",
                style="success" if on else None,
            )
        )
    head = B.heading(f"{E('spark')} audio effects", 2)
    note = B.note(
        "Effects are applied from the next track. "
        f"Up to {effects.MAX_ACTIVE} can be active at once."
    )
    current = B.kv([(f"{E('bolt')} Active", f"<b>{effects.labels(active)}</b>")])
    return (
        head
        + note
        + B.table(None, rows)
        + current
        + B.divider()
        + B.grid(buttons, columns=2)
        + B.row(
            B.btn(f"{E('close')} Reset all", data="v:fx:off", style="danger"),
            B.btn(f"{E('check')} Close", data="v:close"),
        )
    )


def register(client: Client) -> None:
    @client.on_message(filters.command(["effects", "fx", "filter"]))
    async def _effects(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        state = await _active(chat_id)
        arg = command_args(message).strip()
        if not arg:
            await rich.send(client, chat_id, panel(state), reply_to=message.id)
            return

        if not (is_owner(message.from_user.id) or await is_chat_admin(client, chat_id, message.from_user.id)):
            await rich.send(
                client,
                chat_id,
                B.row(B.btn(f"{E('shield')} Admins only", data="v:noop", style="danger")),
            )
            return

        accepted, rejected = effects.parse(arg)
        await chatcfg.set(chat_id, "effects", accepted)
        if runtime.player:
            runtime.player.queues.get(chat_id).effects = accepted

        parts = [B.kv([(f"{E('spark')} Active", f"<b>{effects.labels(accepted)}</b>")])]
        if rejected:
            parts.append(
                B.note(
                    f"{E('warn')} unknown: <code>{rich.esc(', '.join(rejected))}</code>\n"
                    f"try: <code>{', '.join(list(effects.EFFECTS)[:6])}</code>"
                )
            )
        await rich.send(client, chat_id, "".join(parts), reply_to=message.id)


__all__ = ["panel", "register"]
