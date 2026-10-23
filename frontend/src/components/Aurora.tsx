import { useReducedMotionFlag } from "../lib/anim";
import { useEffect, useRef } from "react";
import { webglAvailable } from "../lib/webgl";

/**
 * Aurora — a three.js fragment-shader backdrop.
 *
 * Cheap on purpose: one full-screen quad, five octaves of value noise and a
 * grain pass. It only mounts when WebGL is actually available, pauses when it
 * scrolls out of view or the tab is hidden, and renders a single still frame
 * when the visitor prefers reduced motion.
 */
export function Aurora({ className = "", tone = "violet" }: { className?: string; tone?: "violet" | "cyan" }) {
  const host = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotionFlag();

  useEffect(() => {
    const node = host.current;
    if (!node || !webglAvailable()) return;

    let disposed = false;
    let frame = 0;
    let cleanup: (() => void) | undefined;

    void (async () => {
      const THREE = await import("../lib/three-runtime");
      if (disposed || !host.current) return;

      const parent = host.current;
      const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "low-power" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.setClearColor(0x000000, 0);
      const canvas = renderer.domElement;
      canvas.style.width = "100%";
      canvas.style.height = "100%";
      canvas.style.display = "block";
      parent.appendChild(canvas);

      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

      const palette =
        tone === "cyan"
          ? { a: new THREE.Color("#062033"), b: new THREE.Color("#22d3ee"), c: new THREE.Color("#8b5cf6") }
          : { a: new THREE.Color("#0a0616"), b: new THREE.Color("#8b5cf6"), c: new THREE.Color("#22d3ee") };

      const uniforms = {
        uTime: { value: 0 },
        uRes: { value: new THREE.Vector2(1, 1) },
        uA: { value: palette.a },
        uB: { value: palette.b },
        uC: { value: palette.c },
      };

      const material = new THREE.ShaderMaterial({
        uniforms,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          varying vec2 vUv;
          void main() {
            vUv = uv;
            gl_Position = vec4(position.xy, 0.0, 1.0);
          }
        `,
        fragmentShader: /* glsl */ `
          precision highp float;
          varying vec2 vUv;
          uniform float uTime;
          uniform vec2 uRes;
          uniform vec3 uA;
          uniform vec3 uB;
          uniform vec3 uC;

          float hash(vec2 p) {
            return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
          }
          float noise(vec2 p) {
            vec2 i = floor(p);
            vec2 f = fract(p);
            f = f * f * (3.0 - 2.0 * f);
            float a = hash(i);
            float b = hash(i + vec2(1.0, 0.0));
            float c = hash(i + vec2(0.0, 1.0));
            float d = hash(i + vec2(1.0, 1.0));
            return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
          }
          float fbm(vec2 p) {
            float value = 0.0;
            float amp = 0.55;
            for (int i = 0; i < 5; i++) {
              value += amp * noise(p);
              p *= 2.03;
              amp *= 0.5;
            }
            return value;
          }

          void main() {
            vec2 uv = vUv;
            float aspect = max(uRes.x / max(uRes.y, 1.0), 0.001);
            vec2 p = vec2(uv.x * aspect, uv.y) * 1.7;
            float t = uTime * 0.055;

            float n = fbm(p * 1.25 + vec2(t, -t * 0.65));
            float band = smoothstep(0.25, 0.92, n + 0.16 * sin(p.y * 2.1 + uTime * 0.22));
            vec3 col = mix(uA, uB, band);
            col = mix(col, uC, smoothstep(0.55, 1.0, fbm(p * 0.75 - t * 0.5)) * 0.6);

            float d = distance(uv, vec2(0.52, 0.44));
            float falloff = 1.0 - smoothstep(0.12, 0.92, d);
            float alpha = falloff * (0.55 + 0.45 * band);
            col += (hash(uv * uRes.xy + uTime) - 0.5) * 0.02;

            gl_FragColor = vec4(col, alpha);
          }
        `,
      });

      const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
      quad.frustumCulled = false;
      scene.add(quad);

      const resize = () => {
        const width = parent.clientWidth || 1;
        const height = parent.clientHeight || 1;
        renderer.setSize(width, height, false);
        uniforms.uRes.value.set(width, height);
      };
      resize();

      const clock = new THREE.Clock();
      let visible = true;
      let running = true;

      const render = () => {
        if (!running) return;
        uniforms.uTime.value = clock.getElapsedTime();
        renderer.render(scene, camera);
        if (!reduced) frame = requestAnimationFrame(render);
      };

      const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
      observer?.observe(parent);

      const onVisibility = () => {
        running = !document.hidden && visible;
        cancelAnimationFrame(frame);
        if (running) frame = requestAnimationFrame(render);
      };

      let io: IntersectionObserver | null = null;
      if (typeof IntersectionObserver !== "undefined") {
        io = new IntersectionObserver(
          ([entry]) => {
            visible = entry.isIntersecting;
            if (visible && running && !reduced) {
              cancelAnimationFrame(frame);
              frame = requestAnimationFrame(render);
            }
          },
          { threshold: 0.01 }
        );
        io.observe(parent);
      }

      document.addEventListener("visibilitychange", onVisibility);
      window.addEventListener("resize", resize);

      render();

      cleanup = () => {
        cancelAnimationFrame(frame);
        observer?.disconnect();
        io?.disconnect();
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("resize", resize);
        quad.geometry.dispose();
        material.dispose();
        renderer.dispose();
        canvas.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [tone, reduced]);

  return <div ref={host} className={`aurora ${className}`} aria-hidden="true" data-webgl={webglAvailable() ? "on" : "off"} />;
}
