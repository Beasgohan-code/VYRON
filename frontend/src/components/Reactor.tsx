import { useEffect, useRef, useState } from "react";
import { useReducedMotionFlag } from "../lib/anim";
import { loadThree, visualsWorthLoading, whenIdle } from "../lib/lazy-three";
import { webglAvailable } from "../lib/webgl";

interface ReactorProps {
  className?: string;
  /** Lazily returns the analyser for the shared <audio> element. */
  analyser?: () => AnalyserNode | null;
  playing?: boolean;
  /** Big = the full player stage, small = the dock ornament. */
  size?: "hero" | "dock";
}

/**
 * Reactor — the audio-reactive three.js stage.
 *
 * A displaced icosphere (custom GLSL, value-noise driven) wrapped in a slow
 * wireframe shell and a shell of drifting points. Bass energy drives the
 * displacement and the particle size; treble pushes the shell's rotation.
 * When there is no analyser (paused, unsupported) it breathes on a sine wave,
 * so the stage is never static.
 */
export function Reactor({ className = "", analyser, playing = false, size = "hero" }: ReactorProps) {
  const host = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotionFlag();
  const [supported, setSupported] = useState(true);

  // Keep the live props in a ref: the render loop must not restart on change.
  const live = useRef({ analyser, playing });
  live.current = { analyser, playing };

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    if (!webglAvailable() || !visualsWorthLoading()) {
      setSupported(false);
      return;
    }

    let disposed = false;
    let frame = 0;
    let cleanup: (() => void) | undefined;

    // Wait for the first paint: three.js is a backdrop, not a dependency.
    const cancelIdle = whenIdle(() => void (async () => {
      const THREE = await loadThree();
      if (disposed || !host.current) return;

      const parent = host.current;
      // Phones get a lighter scene: fewer vertices, fewer points, DPR capped.
      const small = typeof window.matchMedia === "function" && window.matchMedia("(max-width: 860px)").matches;
      const renderer = new THREE.WebGLRenderer({ antialias: !small, alpha: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2));
      renderer.setClearColor(0x000000, 0);
      const canvas = renderer.domElement;
      canvas.style.width = "100%";
      canvas.style.height = "100%";
      canvas.style.display = "block";
      parent.appendChild(canvas);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
      camera.position.set(0, 0, 5.6);

      const group = new THREE.Group();
      scene.add(group);

      /* ── the core: a noisy icosphere with a fresnel rim ────────────────── */
      const uniforms = {
        uTime: { value: 0 },
        uBass: { value: 0 },
        uMid: { value: 0 },
        uAmp: { value: 0.18 },
        uColorA: { value: new THREE.Color("#6d28d9") },
        uColorB: { value: new THREE.Color("#7dd3fc") },
      };

      const coreMaterial = new THREE.ShaderMaterial({
        uniforms,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          uniform float uTime;
          uniform float uBass;
          uniform float uAmp;
          varying float vDisp;
          varying vec3 vNormalV;
          varying vec3 vView;

          float hash(vec3 p) {
            return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453123);
          }
          float noise(vec3 p) {
            vec3 i = floor(p);
            vec3 f = fract(p);
            f = f * f * (3.0 - 2.0 * f);
            float n000 = hash(i);
            float n100 = hash(i + vec3(1.0, 0.0, 0.0));
            float n010 = hash(i + vec3(0.0, 1.0, 0.0));
            float n110 = hash(i + vec3(1.0, 1.0, 0.0));
            float n001 = hash(i + vec3(0.0, 0.0, 1.0));
            float n101 = hash(i + vec3(1.0, 0.0, 1.0));
            float n011 = hash(i + vec3(0.0, 1.0, 1.0));
            float n111 = hash(i + vec3(1.0, 1.0, 1.0));
            return mix(
              mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
              mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
              f.z
            );
          }

          void main() {
            vec3 n = normalize(normal);
            float slow = noise(n * 2.2 + vec3(0.0, uTime * 0.32, uTime * 0.17));
            float fast = noise(n * 5.6 - vec3(uTime * 0.21, 0.0, 0.0));
            float disp = (slow * fast - 0.24) * (uAmp + uBass * 0.9);

            vec3 pos = position + n * disp;
            vDisp = disp;

            vec4 mv = modelViewMatrix * vec4(pos, 1.0);
            vNormalV = normalize(normalMatrix * n);
            vView = normalize(-mv.xyz);
            gl_Position = projectionMatrix * mv;
          }
        `,
        fragmentShader: /* glsl */ `
          precision highp float;
          uniform vec3 uColorA;
          uniform vec3 uColorB;
          uniform float uBass;
          varying float vDisp;
          varying vec3 vNormalV;
          varying vec3 vView;

          void main() {
            float rim = pow(1.0 - clamp(dot(vNormalV, vView), 0.0, 1.0), 2.4);
            vec3 col = mix(uColorA, uColorB, clamp(vDisp * 3.2 + 0.45, 0.0, 1.0));
            col += rim * (0.85 + uBass * 0.9);
            float alpha = 0.38 + rim * 0.55;
            gl_FragColor = vec4(col, alpha);
          }
        `,
      });

      // Detail 10 ≈ 7k vertices: smooth enough for the noise, cheap on phones.
      const coreGeometry = new THREE.IcosahedronGeometry(1.28, size === "dock" || small ? 7 : 10);
      const core = new THREE.Mesh(coreGeometry, coreMaterial);
      group.add(core);

      /* ── wireframe shell ──────────────────────────────────────────────── */
      const shellGeometry = new THREE.IcosahedronGeometry(1.78, 2);
      const shellMaterial = new THREE.MeshBasicMaterial({
        color: 0x8b5cf6,
        wireframe: true,
        transparent: true,
        opacity: 0.22,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const shell = new THREE.Mesh(shellGeometry, shellMaterial);
      group.add(shell);

      /* ── drifting particles on a shell ────────────────────────────────── */
      const count = size === "dock" ? 260 : small ? 420 : 900;
      const positions = new Float32Array(count * 3);
      for (let i = 0; i < count; i += 1) {
        const radius = 1.9 + Math.random() * 2.4;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = radius * Math.cos(phi) * 0.75;
        positions[i * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
      }
      const dustGeometry = new THREE.BufferGeometry();
      dustGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const dustMaterial = new THREE.PointsMaterial({
        color: 0xc4b5fd,
        size: size === "dock" ? 0.03 : 0.024,
        transparent: true,
        opacity: 0.7,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      });
      const dust = new THREE.Points(dustGeometry, dustMaterial);
      group.add(dust);

      /* ── resize + loop ────────────────────────────────────────────────── */
      const resize = () => {
        const width = parent.clientWidth || 1;
        const height = parent.clientHeight || 1;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        const scale = Math.min(1.15, Math.max(0.62, Math.min(width, height) / 460));
        group.scale.setScalar(scale);
      };
      resize();

      const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
      observer?.observe(parent);

      // Mobile GPUs drop contexts under memory pressure: stop drawing and show
      // the CSS orb instead of leaving a frozen canvas on screen.
      const onContextLost = (event: Event) => {
        event.preventDefault();
        running = false;
        cancelAnimationFrame(frame);
        canvas.style.display = "none";
        setSupported(false);
      };
      canvas.addEventListener("webglcontextlost", onContextLost);

      const clock = new THREE.Clock();
      const spectrum = new Uint8Array(64);
      let level = 0;
      let bass = 0;
      let treble = 0;
      let running = true;

      const sample = () => {
        const node = live.current.analyser?.() ?? null;
        if (!node) {
          // idle breathing so the stage never looks frozen
          const t = clock.getElapsedTime();
          level = 0.16 + 0.1 * Math.sin(t * 0.9);
          bass = 0.14 + 0.12 * Math.sin(t * 0.6 + 1.2);
          treble = 0.1;
          return;
        }
        const data = node.frequencyBinCount > spectrum.length ? spectrum.subarray(0, spectrum.length) : spectrum;
        node.getByteFrequencyData(data as Uint8Array<ArrayBuffer>);
        const bins = data.length;
        const slice = (from: number, to: number) => {
          let sum = 0;
          for (let i = from; i < to; i += 1) sum += data[i];
          return sum / Math.max(1, to - from) / 255;
        };
        bass = slice(0, Math.floor(bins * 0.18));
        const mid = slice(Math.floor(bins * 0.18), Math.floor(bins * 0.6));
        treble = slice(Math.floor(bins * 0.6), bins);
        level = Math.max(bass, mid, treble);
      };

      const tick = () => {
        if (!running) return;
        const elapsed = clock.getElapsedTime();
        sample();

        uniforms.uTime.value = elapsed;
        const smooth = (current: number, next: number) => current + (next - current) * 0.12;
        uniforms.uBass.value = smooth(uniforms.uBass.value, live.current.playing ? bass : bass * 0.35);
        uniforms.uMid.value = smooth(uniforms.uMid.value, treble);

        group.rotation.y = elapsed * 0.16 + treble * 0.5;
        group.rotation.x = Math.sin(elapsed * 0.3) * 0.14 + bass * 0.16;
        core.rotation.z = elapsed * 0.05;

        shell.rotation.y = -elapsed * 0.24;
        shell.rotation.x = elapsed * 0.09;
        shellMaterial.opacity = 0.14 + treble * 0.35 + bass * 0.12;

        dust.rotation.y = elapsed * 0.05;
        dust.rotation.x = Math.sin(elapsed * 0.12) * 0.12;
        dustMaterial.size = (size === "dock" ? 0.028 : 0.022) + bass * 0.03;

        camera.position.z = 5.6 - level * 0.45;
        renderer.render(scene, camera);

        if (!reduced) frame = requestAnimationFrame(tick);
      };
      tick();

      let onScreen = true;
      let io: IntersectionObserver | null = null;
      if (typeof IntersectionObserver !== "undefined") {
        io = new IntersectionObserver(
          ([entry]) => {
            onScreen = entry.isIntersecting;
            running = onScreen && !document.hidden;
            cancelAnimationFrame(frame);
            if (running && !reduced) frame = requestAnimationFrame(tick);
          },
          { threshold: 0.01 }
        );
        io.observe(parent);
      }

      const onVisibility = () => {
        running = !document.hidden && onScreen;
        cancelAnimationFrame(frame);
        if (running && !reduced) frame = requestAnimationFrame(tick);
      };
      document.addEventListener("visibilitychange", onVisibility);

      cleanup = () => {
        cancelAnimationFrame(frame);
        observer?.disconnect();
        io?.disconnect();
        canvas.removeEventListener("webglcontextlost", onContextLost);
        document.removeEventListener("visibilitychange", onVisibility);
        coreGeometry.dispose();
        coreMaterial.dispose();
        shellGeometry.dispose();
        shellMaterial.dispose();
        dustGeometry.dispose();
        dustMaterial.dispose();
        renderer.dispose();
        canvas.remove();
      };
    })());

    return () => {
      disposed = true;
      cancelIdle();
      cleanup?.();
    };
  }, [size, reduced]);

  return (
    <div
      ref={host}
      className={`reactor ${className}`}
      aria-hidden="true"
      data-playing={playing ? "on" : "off"}
      data-webgl={supported ? "on" : "off"}
    >
      {!supported && <span className="reactor-fallback" />}
    </div>
  );
}
