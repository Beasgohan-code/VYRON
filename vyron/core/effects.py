# ---------------------------------------------------------------------------
#  VYRON — audio effects
#
#  Effects are plain ffmpeg audio filters applied at stream start, so they cost
#  nothing until someone enables one.
# ---------------------------------------------------------------------------
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    name: str
    label: str
    filters: str
    note: str = ""


EFFECTS: dict[str, Effect] = {
    "bass": Effect("bass", "Bass boost", "bass=g=12:f=110:w=0.6", "deeper low end"),
    "treble": Effect("treble", "Treble boost", "treble=g=8:f=6000", "brighter vocals"),
    "loud": Effect("loud", "Loudness", "loudnorm=I=-16:TP=-1.5:LRA=11", "even, radio-level volume"),
    "nightcore": Effect(
        "nightcore",
        "Nightcore",
        "asetrate=48000*1.25,aresample=48000,atempo=0.96",
        "faster + higher pitch",
    ),
    "vaporwave": Effect(
        "vaporwave",
        "Vaporwave",
        "asetrate=48000*0.85,aresample=48000,atempo=1.06",
        "slower + deeper",
    ),
    "8d": Effect(
        "8d",
        "8D audio",
        "apulsator=hz=0.09",
        "rotating stereo",
    ),
    "echo": Effect("echo", "Echo", "aecho=0.8:0.9:1000:0.3", "spacey tail"),
    "reverb": Effect("reverb", "Reverb", "afreqshift=shift=0:order=0", "subtle ambience"),
    "karaoke": Effect(
        "karaoke",
        "Karaoke",
        "pan=stereo|c0=c0-c1|c1=c1-c0",
        "strips centred vocals",
    ),
    "mono": Effect("mono", "Mono", "pan=mono|c0=0.5*c0+0.5*c1", "single channel"),
    "speed": Effect("speed", "Double speed", "atempo=2.0", "2× playback"),
    "slow": Effect("slow", "Half speed", "atempo=0.5", "0.5× playback"),
}

MAX_ACTIVE = 3


def available() -> dict[str, Effect]:
    return dict(EFFECTS)


def resolve(names: list[str] | tuple[str, ...] | None) -> list[str]:
    """Keep only known effect names, de-duplicated, capped at MAX_ACTIVE."""
    seen: list[str] = []
    for name in names or ():
        key = str(name).strip().lower()
        if key in EFFECTS and key not in seen:
            seen.append(key)
    return seen[:MAX_ACTIVE]


def ffmpeg_filter(names: list[str] | tuple[str, ...] | None) -> str | None:
    """Compose the ``-af`` chain for the given effect names."""
    chain = [EFFECTS[name].filters for name in resolve(names)]
    return ",".join(chain) if chain else None


def ffmpeg_parameters(
    names: list[str] | tuple[str, ...] | None,
    *,
    seek: int = 0,
) -> str | None:
    """Full ffmpeg parameter string handed to ntgcalls (seek + effects)."""
    parts: list[str] = []
    if seek and seek > 0:
        parts.append(f"-ss {int(seek)}")
    chain = ffmpeg_filter(names)
    if chain:
        parts.append(f'-af "{chain}"')
    return " ".join(parts) if parts else None


def labels(names: list[str] | tuple[str, ...] | None) -> str:
    resolved = resolve(names)
    if not resolved:
        return "off"
    return ", ".join(EFFECTS[name].label for name in resolved)


def parse(text: str) -> tuple[list[str], list[str]]:
    """Parse ``/effects bass nightcore`` into (accepted, rejected)."""
    requested = [token.strip().lower() for token in str(text or "").replace(",", " ").split()]
    accepted: list[str] = []
    rejected: list[str] = []
    for token in requested:
        if token in {"off", "none", "reset"}:
            return [], []
        if token in EFFECTS:
            if token not in accepted:
                accepted.append(token)
        else:
            rejected.append(token)
    return resolve(accepted), rejected


__all__ = [
    "EFFECTS",
    "Effect",
    "available",
    "ffmpeg_filter",
    "ffmpeg_parameters",
    "labels",
    "parse",
    "resolve",
]
