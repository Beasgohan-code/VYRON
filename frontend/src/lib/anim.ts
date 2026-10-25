/**
 * Anime.js helpers — every animation in the Mini App funnels through here so
 * that `prefers-reduced-motion` and unmounts are handled in one place.
 */
import { animate, stagger } from "animejs";
import { useEffect, useRef, useState } from "react";

export function reducedMotion(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  } catch {
    return false;
  }
}

/** React state form of :func:`reducedMotion` (updates live). */
export function useReducedMotionFlag(): boolean {
  const [reduced, setReduced] = useState(reducedMotion);
  useEffect(() => {
    let query: MediaQueryList | undefined;
    try {
      query = window.matchMedia?.("(prefers-reduced-motion: reduce)") ?? undefined;
    } catch {
      query = undefined;
    }
    if (!query) return;
    const listener = () => setReduced(query?.matches ?? false);
    query.addEventListener?.("change", listener);
    return () => query.removeEventListener?.("change", listener);
  }, []);
  return reduced;
}

const nodes = (target: Element[] | NodeListOf<Element> | null | undefined): HTMLElement[] => {
  if (!target) return [];
  if (target instanceof NodeList) return Array.from(target) as HTMLElement[];
  return (target as Element[]).filter(Boolean) as HTMLElement[];
};

/** Fade + rise a group of nodes, staggered. Falls back to "just show it". */
export function reveal(
  target: Element[] | NodeListOf<Element> | null | undefined,
  options: { y?: number; delay?: number; duration?: number; scale?: number } = {}
): void {
  const list = nodes(target);
  if (!list.length) return;

  list.forEach((node) => {
    node.style.opacity = "1";
  });
  if (reducedMotion()) {
    list.forEach((node) => {
      node.style.transform = "none";
    });
    return;
  }

  const params: Record<string, unknown> = {
    opacity: [0, 1],
    y: [options.y ?? 16, 0],
    duration: options.duration ?? 620,
    delay: stagger(options.delay ?? 45),
    ease: "out(3)",
  };
  if (options.scale !== undefined) params.scale = [options.scale, 1];
  animate(list, params as Parameters<typeof animate>[1]);
}

/** A single element: scale-in with a soft spring. */
export function popIn(target: HTMLElement | null, options: { delay?: number; duration?: number } = {}): void {
  if (!target) return;
  if (reducedMotion()) {
    target.style.opacity = "1";
    return;
  }
  animate(target, {
    opacity: [0, 1],
    scale: [0.94, 1],
    duration: options.duration ?? 480,
    delay: options.delay ?? 0,
    ease: "out(4)",
  });
}

/** Count a number up inside `node` (keeps its prefix/suffix). */
export function countUp(node: HTMLElement | null, value: number, duration = 900): void {
  if (!node) return;
  if (reducedMotion() || !Number.isFinite(value)) {
    node.textContent = String(value);
    return;
  }
  const state = { value: 0 };
  animate(state, {
    value,
    duration,
    ease: "out(3)",
    onUpdate: () => {
      node.textContent = String(Math.round(state.value));
    },
    onComplete: () => {
      node.textContent = String(value);
    },
  });
}

/** Small attention nudge for a control that just changed state. */
export function nudge(target: HTMLElement | null): void {
  if (!target || reducedMotion()) return;
  animate(target, {
    scale: [1, 1.16, 1],
    duration: 420,
    ease: "inOut(2)",
  });
}

/** Pulse a value change: the element briefly glows with the accent colour. */
export function flash(target: HTMLElement | null): void {
  if (!target || reducedMotion()) return;
  animate(target, {
    opacity: [0.4, 1],
    y: [4, 0],
    duration: 420,
    ease: "out(3)",
  });
}

/**
 * Pointer-driven 3D tilt, smoothed through anime.js. Desktop only: touch
 * devices and reduced-motion users get a perfectly still card.
 */
export function useTilt<T extends HTMLElement>(strength = 7) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || reducedMotion()) return;
    if (window.matchMedia?.("(hover: none)")?.matches) return;

    let pending: number | null = null;
    let point = { x: 0, y: 0 };

    const apply = () => {
      pending = null;
      animate(node, {
        rotateY: point.x * strength,
        rotateX: -point.y * strength,
        translateZ: 12,
        duration: 420,
        ease: "out(3)",
      });
    };

    const onMove = (event: PointerEvent) => {
      const rect = node.getBoundingClientRect();
      point = {
        x: (event.clientX - rect.left) / Math.max(1, rect.width) - 0.5,
        y: (event.clientY - rect.top) / Math.max(1, rect.height) - 0.5,
      };
      if (!pending) pending = requestAnimationFrame(apply);
    };

    const onLeave = () => {
      if (pending) cancelAnimationFrame(pending);
      pending = null;
      animate(node, { rotateY: 0, rotateX: 0, translateZ: 0, duration: 640, ease: "out(4)" });
    };

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);
    return () => {
      if (pending) cancelAnimationFrame(pending);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    };
  }, [strength]);
  return ref;
}

/**
 * Reveal the direct children of a view whenever `key` changes.
 * Attach the returned ref to the scrolling container.
 */
export function useViewReveal<T extends HTMLElement>(key: unknown, selector = ":scope > *") {
  const ref = useRef<T>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const targets = root.querySelectorAll(selector);
    reveal(targets, { y: 18, delay: 40, duration: 560 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return ref;
}

/** Animate a list of rows in whenever they first render (or change length). */
export function useStagger<T extends HTMLElement>(count: number, selector = ":scope > *") {
  const ref = useRef<T>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    reveal(root.querySelectorAll(selector), { y: 12, delay: 35, duration: 480 });
  }, [count, selector]);
  return ref;
}
