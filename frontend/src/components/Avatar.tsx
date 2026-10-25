import { useEffect, useState } from "react";
import { avatarSeed, cachedAvatar, loadAvatar } from "../lib/avatar";
import { hashOf, initials } from "../lib/format";

interface Props {
  name?: string;
  /** `state.user.photo` — the signed Telegram URL, used only as a cache seed. */
  photo?: string;
  userId?: number;
  /** Rendered size in px. */
  size?: number;
  className?: string;
  /** Accent ring around the picture (the profile card). */
  ring?: boolean;
  /** A small status dot in the corner: voice chat ready, or not. */
  status?: "on" | "off" | null;
  /** Rounded square instead of a circle. */
  shape?: "circle" | "squircle";
  title?: string;
}

/**
 * The user's Telegram profile picture, or their initials.
 *
 * Order of preference: the picture already on this device (instant), the
 * picture from the server (a beat later), the initials. The initials are drawn
 * *under* the image, so a slow load shows a real avatar rather than a hole, and
 * a user who hides their picture still gets something personal.
 */
export function Avatar({
  name,
  photo,
  userId,
  size = 40,
  className = "",
  ring = false,
  status = null,
  shape = "circle",
  title,
}: Props) {
  const seed = avatarSeed({ id: userId, photo });
  const [src, setSrc] = useState<string | null>(() => cachedAvatar(seed));
  const [loaded, setLoaded] = useState(false);
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    setBroken(false);
    setSrc(cachedAvatar(seed));
    setLoaded(false);
    if (!seed) return;
    let live = true;
    void loadAvatar(seed).then((data) => {
      if (live && data) setSrc(data);
    });
    return () => {
      live = false;
    };
  }, [seed]);

  const hue = hashOf(name || String(userId ?? "vyron")) % 360;
  const showImage = Boolean(src) && !broken;
  const label = name?.trim() || "Listener";

  return (
    <span
      className={`avatar avatar-${shape} ${ring ? "avatar-ring" : ""} ${className}`.trim()}
      style={{
        width: size,
        height: size,
        // Deterministic colour per person: the same initials always match their
        // own gradient, on every device.
        ["--av-h" as string]: hue,
        ["--av-size" as string]: `${Math.max(10, Math.round(size * 0.38))}px`,
      }}
      title={title ?? label}
      role="img"
      aria-label={showImage ? `${label}'s picture` : label}
    >
      <span className="avatar-initials" aria-hidden="true">
        {initials(name)}
      </span>
      {showImage && (
        <img
          className={`avatar-img ${loaded ? "in" : ""}`}
          src={src ?? undefined}
          alt=""
          draggable={false}
          decoding="async"
          loading="eager"
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          onError={() => setBroken(true)}
        />
      )}
      {status && <i className={`avatar-status ${status}`} aria-hidden="true" />}
    </span>
  );
}
