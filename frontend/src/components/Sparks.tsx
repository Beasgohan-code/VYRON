import { animate } from "animejs";
import { useEffect, useRef } from "react";
import { reducedMotion } from "../lib/anim";

/**
 * Sparks — anime.js embers drifting up behind the player artwork.
 * Fourteen DOM nodes, no canvas: cheap, and it stops dead when paused.
 */
export function Sparks({ active }: { active: boolean }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = host.current;
    if (!root || !active || reducedMotion()) return;
    const nodes = Array.from(root.querySelectorAll<HTMLElement>(".spark"));
    if (!nodes.length) return;

    const animations = nodes.map((node, index) =>
      animate(node, {
        y: [0, -110 - Math.random() * 130],
        x: [0, (Math.random() - 0.5) * 90],
        opacity: [0, 0.9, 0],
        scale: [0.5, 1.15],
        duration: 4200 + Math.random() * 2400,
        delay: index * 260,
        loop: true,
        ease: "inOutSine",
      })
    );

    return () => {
      animations.forEach((animation) => {
        try {
          animation.pause();
        } catch {
          /* older anime builds */
        }
      });
    };
  }, [active]);

  return (
    <div ref={host} className={`sparks ${active ? "on" : ""}`} aria-hidden="true">
      {Array.from({ length: 14 }, (_, index) => (
        <span
          key={index}
          className="spark"
          style={{
            left: `${6 + Math.random() * 88}%`,
            top: `${28 + Math.random() * 60}%`,
            ["--hue" as string]: index % 2 ? "var(--accent-2)" : "var(--accent)",
          }}
        />
      ))}
    </div>
  );
}
