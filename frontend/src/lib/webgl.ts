/** Tiny capability probe — keeps three.js out of jsdom and old browsers. */
export function webglAvailable(): boolean {
  // jsdom (tests) and very old browsers have no WebGL constructor at all —
  // bail before touching a canvas so nothing logs "getContext not implemented".
  if (typeof WebGLRenderingContext === "undefined" && typeof WebGL2RenderingContext === "undefined") {
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    return Boolean(gl);
  } catch {
    return false;
  }
}

export function reducedMotion(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  } catch {
    return false;
  }
}
