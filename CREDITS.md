# Credits & attribution

VYRON is an independent implementation, but it stands on the shoulders of some
excellent open-source projects. Everything below is MIT-licensed unless noted.

## Directly used as dependencies

| Project | Author | Role in VYRON |
|---|---|---|
| [Kurigram](https://github.com/KurimuzonAkuma/kurigram) | KurimuzonAkuma | Telegram client with Bot API 10.3 support (rich messages, ephemeral cards) — the base library installed as `kurigram` |
| [richgram](https://github.com/Badmunda05/richgram) | [BadmundaXd](https://t.me/BadmundaXd) | Rich-message helpers: coloured buttons, tables, details, drafts, plain-text fallback. VYRON's `vyron/ui/blocks.py` is a themed wrapper around it |
| [PyTgCalls](https://github.com/pytgcalls/pytgcalls) + [ntgcalls](https://github.com/pytgcalls/ntgcalls) | MarshalX / pytgcalls org | Voice-chat streaming engine |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | yt-dlp contributors | Search, stream resolution, downloads |
| [LRCLIB](https://lrclib.net) | LRCLIB | Free synced/plain lyrics API |
| [Telegram Bot API](https://core.telegram.org/bots/api) | Telegram | Rich message format, custom emoji, Mini Apps |

## Feature & design inspiration

| Project | Author | What VYRON took from it |
|---|---|---|
| [**Videl**](https://github.com/Beasgohan-code/Videl) | [Beasgohan-code](https://github.com/Beasgohan-code) | Feature scope and structure: search picker, effects module, content locks + anti-flood panel, group-management commands (ban/kick/mute/warn/purge/pin/welcome/goodbye), channel play (`/cplay`), playlist handling, idle auto-leave. VYRON re-implements these on its own async runtime rather than forking the code |
| [**FallenMusic**](https://github.com/AnonymousX1025/FallenMusic) | [AnonymousX1025](https://github.com/AnonymousX1025) | Operational command surface: `activevc`, `leaveall`, `sysstats`, broadcast/gcast, sudoers-only maintenance, empty-VC watcher idea, thumbnail/caption conventions |
| [**ShizuMusic**](https://github.com/Badmunda05/ShizuMusic) | [BadmundaXd](https://github.com/Badmunda05) | Reference for Bot API 10.3 + PyTgCalls integration patterns |
| [**richgram**](https://github.com/Badmunda05/richgram) | [BadmundaXd](https://github.com/Badmunda05) | UI vocabulary for VYRON's cards (and the library itself — see above) |

## Notes on originality

- No Videl or FallenMusic source file was copied into this repository. Their
  **feature sets and command names** (which are common across Telegram music
  bots) informed the roadmap; every line here was written for VYRON's
  `runtime` / `ui` / `core` architecture and is covered by VYRON's own tests.
- The MIT badge in the README refers to VYRON itself. Dependencies keep their
  own licenses — see each project above.

## Assets

- `assets/banner.png` — original artwork generated for VYRON.
- Emoji glyphs in `vyron/ui/theme.py` are standard Unicode emoji; premium
  overrides come from whatever sticker pack *you* choose to link.

## Contributing credit

If you add a feature inspired by another project, add a row here — keeping the
chain of credit visible is a condition of the MIT spirit these projects share.
