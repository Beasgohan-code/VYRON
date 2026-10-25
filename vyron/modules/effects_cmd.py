# ---------------------------------------------------------------------------
#  VYRON — /effects (ffmpeg filters applied to the live stream)
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client
from pyrogram.types import Message

from vyron.core import chatcfg, effects
from vyron.runtime import runtime
from vyron.ui import blocks as B, cards
from vyron.ui import rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, is_chat_admin, is_owner
from vyron.utils.commands import cmd


async def _active(chat_id: int) -> list[str]:
    return effects.resolve(await chatcfg.get(chat_id, "effects", []) or [])


async def save(chat_id: int, names: list[str]) -> bool:
    """Store the filters and make the *playing* song follow them.

    Both the /effects card and the button board go through here, so a filter
    cannot be saved in one place and silently ignored by the other. Returns
    True when a live stream was restarted at its current position.
    """
    active = effects.resolve(names)
    await chatcfg.set(chat_id, "effects", active)
    if not runtime.player:
        return False
    runtime.player.queues.get(chat_id).effects = active
    return await runtime.player.reapply_effects(chat_id)


def _heard(live: bool, when_next: str) -> str:
    """The one line that says whether they can hear it yet."""
    if live:
        return "Heard right now — the track picked up at this second."
    return when_next


def panel(active: list[str]) -> str:
    """The effects board — every filter, what it sounds like, one tap each."""
    rows: list[tuple[str, str, str]] = []
    buttons: list[str] = []
    for name, effect in effects.EFFECTS.items():
        on = name in active
        rows.append((("check" if on else ""), effect.label, f"<i>{effect.note}</i>"))
        buttons.append(
            B.btn(
                f"{'●' if on else '○'} {effect.label}",
                data=f"v:fx:{name}",
                style="success" if on else None,
            )
        )
    return (
        B.soft_header(
            "spark",
            "Audio Effects",
            f"{len(active)}/{effects.MAX_ACTIVE} active · live stream follows immediately",
        )
        + B.pretty_table([
            ("Active", f"<b>{effects.labels(active) or 'none'}</b>"),
            ("Limit", f"up to <b>{effects.MAX_ACTIVE}</b> at once"),
        ])
        + B.note(
            "Changes the sound of the live stream. A song already playing picks "
            "the new filter up from the current second — it does not jump back."
        )
        + B.section_title("Available")
        + B.items(rows)
        + B.actions(
            B.grid(buttons, columns=2),
            B.row(
                B.btn(f"{E('cross')} Reset all", data="v:fx:off", style="danger"),
                B.btn(f"{E('close')} Done", data="v:close", style="danger"),
            ),
        )
        + B.soft_footer("tap to toggle", "live")
    )


def register(client: Client) -> None:
    @client.on_message(cmd(["effects"]))
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
                cards.change_card(
                    "admins only",
                    glyph="shield",
                    label="who can change this",
                    value="chat admins",
                    note="Ask an admin of this group, or the bot owner, to switch effects on.",
                    actions=B.row(B.btn(f"{E('spark')} The board", data="v:fx", style="primary")),
                ),
            )
            return

        accepted, rejected = effects.parse(arg)
        live = await save(chat_id, accepted)

        await rich.send(
            client,
            chat_id,
            cards.change_card(
                "effects updated",
                glyph="spark",
                label="active",
                value=f"<b>{effects.labels(accepted)}</b>",
                note=(
                    "One of those is not a filter I know — the rest were kept. "
                    + _heard(live, "They apply from the next track.")
                    if rejected
                    else _heard(live, "Applied from the next track.")
                ),
                extra=(
                    [("warn", "ignored", f"<code>{rich.esc(', '.join(rejected))}</code>")]
                    if rejected
                    else []
                ),
                actions=B.row(
                    B.btn(f"{E('spark')} The board", data="v:fx", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )



    # ── single-effect shortcuts ────────────────────────────────────────────
    async def _toggle_effect(message: Message, name: str, enable: bool) -> None:
        chat_id = message.chat.id
        if not (
            is_owner(message.from_user.id)
            or await is_chat_admin(client, chat_id, message.from_user.id)
        ):
            await rich.send(
                client,
                chat_id,
                cards.change_card(
                    "admins only",
                    glyph="shield",
                    label="who can change this",
                    value="chat admins",
                    note="Ask an admin of this group, or the bot owner, to switch effects on.",
                    actions=B.row(B.btn(f"{E('spark')} The board", data="v:fx", style="primary")),
                ),
            )
            return
        current = await _active(chat_id)
        if enable:
            if name in current:
                await rich.send(
                    client,
                    chat_id,
                    cards.change_card(
                        "already on",
                        glyph="info",
                        label="filter",
                        value=f"<b>{effects.EFFECTS[name].label}</b>",
                        note="It is already shaping the stream — nothing changed.",
                        actions=B.row(
                            B.btn(f"{E('spark')} The board", data="v:fx", style="primary"),
                            B.btn(f"{E('close')} Close", data="v:close"),
                        ),
                    ),
                    reply_to=message.id,
                )
                return
            updated = effects.resolve([*current, name])
        else:
            updated = [item for item in current if item != name]
        live = await save(chat_id, updated)
        await rich.send(
            client,
            chat_id,
            cards.change_card(
                f"{effects.EFFECTS[name].label} {'on' if enable else 'off'}",
                glyph="check" if enable else "cross",
                label="active",
                value=f"<b>{effects.labels(updated)}</b>",
                note=_heard(live, "The next track comes through with it."),
                actions=B.row(
                    B.btn(f"{E('spark')} The board", data="v:fx", style="primary"),
                    B.btn("↩ Undo", data=f"v:fx:{name}"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["effecton"]))
    async def _effect_on(_: Client, message: Message) -> None:
        name = effects.resolve([command_args(message).strip()])
        if not name:
            names = ", ".join(effects.EFFECTS)
            await rich.send(client, message.chat.id, cards.warn_card(f"Which filter? Pick one: <code>{names}</code>"))
            return
        await _toggle_effect(message, name[0], True)

    @client.on_message(cmd(["effectoff"]))
    async def _effect_off(_: Client, message: Message) -> None:
        arg = command_args(message).strip()
        if not arg:
            live = await save(message.chat.id, [])
            await rich.send(
                client,
                message.chat.id,
                cards.change_card(
                    "effects cleared",
                    glyph="cross",
                    label="active",
                    value="<b>none</b>",
                    note=_heard(live, "The stream is back to the original audio from the next track."),
                    actions=B.row(
                        B.btn(f"{E('spark')} The board", data="v:fx", style="primary"),
                        B.btn(f"{E('close')} Close", data="v:close"),
                    ),
                ),
                reply_to=message.id,
            )
            return
        name = effects.resolve([arg])
        if not name:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    "That is not a filter I know. Send <code>/effects</code> to see the board."
                ),
                reply_to=message.id,
            )
            return
        await _toggle_effect(message, name[0], False)

    def _make_shortcut(effect_name: str):
        async def _on(_: Client, message: Message) -> None:
            await _toggle_effect(message, effect_name, True)

        async def _off(_: Client, message: Message) -> None:
            await _toggle_effect(message, effect_name, False)

        return _on, _off

    for effect_name in ("bass", "nightcore", "vaporwave"):
        on_handler, off_handler = _make_shortcut(effect_name)
        client.on_message(cmd([effect_name]))(on_handler)
        client.on_message(cmd(["{shortcut}off"]))(off_handler)



__all__ = ["panel", "register"]
