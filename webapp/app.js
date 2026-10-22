/* ───────────────────────────────────────────────────────────────────────────
   VYRON Player — Mini App logic
   Talks to /api/state and /api/action; degrades to a read-only demo when the
   page is opened outside Telegram (handy for design work).
   ─────────────────────────────────────────────────────────────────────────── */
(() => {
  "use strict";

  const tg = window.Telegram?.WebApp;
  const params = new URLSearchParams(location.search);
  const token = params.get("t") || "";

  const $ = (id) => document.getElementById(id);
  const state = {
    data: null,
    tab: "player",
    preview: false,
    dragging: false,
    timer: null,
  };

  // ── Telegram bootstrap ──────────────────────────────────────────────────
  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("#0a0a11"); tg.setBackgroundColor("#0a0a11"); } catch (_) {}
  } else {
    state.preview = true;
    $("preview-ribbon").hidden = false;
  }

  const haptic = (style = "light") => {
    try { tg?.HapticFeedback?.impactOccurred(style); } catch (_) {}
  };

  // ── helpers ─────────────────────────────────────────────────────────────
  const fmt = (seconds) => {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
             : `${m}:${String(s).padStart(2, "0")}`;
  };

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let toastTimer = null;
  const toast = (message) => {
    const el = $("toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
  };

  async function api(path, body) {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Init-Data": tg?.initData || "",
        "X-Vyron-Token": token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({ ok: false }));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  async function act(action, value) {
    haptic();
    if (state.preview) {
      toast("Open this app from Telegram to control playback");
      return null;
    }
    try {
      const result = await api("/api/action", { action, value });
      await refresh();
      return result;
    } catch (error) {
      toast(error.message || "Action failed");
      return null;
    }
  }

  // ── rendering ───────────────────────────────────────────────────────────
  function renderNow(now, settings) {
    const hasTrack = Boolean(now);
    $("track-title").textContent = hasTrack ? now.title : "Nothing playing";
    $("track-artist").textContent = hasTrack
      ? now.uploader || "unknown artist"
      : "Send /play in the chat to start";

    const cover = $("cover");
    if (hasTrack && now.thumbnail) {
      cover.src = now.thumbnail;
      cover.style.display = "block";
      $("cover-fallback").style.display = "none";
    } else {
      cover.removeAttribute("src");
      cover.style.display = "none";
      $("cover-fallback").style.display = "grid";
    }

    $("chip-source").textContent = hasTrack ? (now.source || "youtube") : "idle";
    $("chip-quality").textContent = "high";
    const requester = $("chip-requester");
    if (hasTrack && now.requested_by) {
      requester.hidden = false;
      requester.textContent = `for ${now.requested_by}`;
    } else {
      requester.hidden = true;
    }

    if (!state.dragging) {
      const elapsed = hasTrack ? now.elapsed || 0 : 0;
      const total = hasTrack ? now.duration || 0 : 0;
      const percent = total ? Math.min(100, (elapsed / total) * 100) : 0;
      const seek = $("seek");
      seek.value = percent;
      seek.style.setProperty("--p", `${percent}%`);
      seek.disabled = !hasTrack;
      $("time-elapsed").textContent = fmt(elapsed);
      $("time-total").textContent = total ? fmt(total) : "live";
    }

    const paused = Boolean(hasTrack && now.paused);
    $("play").classList.toggle("paused", paused);
    $("play-icon").innerHTML = paused
      ? '<path d="M8 5h3v14H8zM13 5h3v14h-3z"/>'
      : '<path d="M8 5v14l11-7z"/>';

    const volume = Number(settings?.volume ?? now?.volume ?? 100);
    if (document.activeElement !== $("volume")) {
      $("volume").value = volume;
      $("volume").style.setProperty("--p", `${(volume / 200) * 100}%`);
    }
    $("volume-value").textContent = `${volume}%`;

    document.querySelector('[data-action="autoplay"]')
      ?.classList.toggle("on", Boolean(settings?.autoplay));
    document.querySelector('[data-action="always"]')
      ?.classList.toggle("on", Boolean(settings?.always_on));
  }

  function renderQueue(queue) {
    const list = $("queue-list");
    $("queue-count").textContent = queue.length;
    $("queue-empty").hidden = queue.length > 0;
    list.innerHTML = queue
      .map(
        (track) => `
        <li class="item" data-index="${track.index}">
          <span class="item-idx">${track.index}</span>
          ${track.thumbnail ? `<img class="item-art" src="${esc(track.thumbnail)}" alt="" />` : '<div class="item-art"></div>'}
          <div class="item-body">
            <div class="item-title">${esc(track.title)}</div>
            <div class="item-sub">${esc(track.uploader || "unknown")} · ${fmt(track.duration)}</div>
          </div>
          <div class="item-actions">
            <button class="icon-btn" data-queue="jump" aria-label="Play now">
              <svg viewBox="0 0 24 24"><path d="M7 5v14l10-7z"/></svg>
            </button>
            <button class="icon-btn" data-queue="remove" aria-label="Remove">
              <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
            </button>
          </div>
        </li>`
      )
      .join("");
  }

  function renderResults(results) {
    const list = $("search-results");
    $("search-hint").hidden = results.length > 0;
    list.innerHTML = results
      .map(
        (track) => `
        <li class="item" data-query="${esc(track.title)}">
          ${track.thumbnail ? `<img class="item-art" src="${esc(track.thumbnail)}" alt="" />` : '<div class="item-art"></div>'}
          <div class="item-body">
            <div class="item-title">${esc(track.title)}</div>
            <div class="item-sub">${esc(track.uploader || "unknown")} · ${fmt(track.duration)}</div>
          </div>
          <button class="icon-btn" aria-label="Play">
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
          </button>
        </li>`
      )
      .join("");
  }

  function renderFavorites(items) {
    const list = $("fav-list");
    $("fav-empty").hidden = items.length > 0;
    list.innerHTML = items
      .map(
        (track) => `
        <li class="item">
          ${track.thumbnail ? `<img class="item-art" src="${esc(track.thumbnail)}" alt="" />` : '<div class="item-art"></div>'}
          <div class="item-body">
            <div class="item-title">${esc(track.title)}</div>
            <div class="item-sub">${esc(track.uploader || "unknown")} · ${fmt(track.duration)}</div>
          </div>
        </li>`
      )
      .join("");
  }

  function renderSettings(settings) {
    document.querySelector('[data-setting="autoplay"]').checked = Boolean(settings.autoplay);
    document.querySelector('[data-setting="always"]').checked = Boolean(settings.always_on);
    $("loop-select").value = settings.loop || "off";
  }

  // ── data loading ────────────────────────────────────────────────────────
  const demo = {
    ok: true,
    version: "1.0.0",
    streaming: true,
    user: { id: 0, name: "Guest" },
    chat: { id: 0, title: "Preview" },
    now: {
      title: "Midnight Drive",
      uploader: "VYRON Demo",
      duration: 212,
      elapsed: 74,
      paused: false,
      source: "youtube",
      requested_by: "you",
      thumbnail: "",
    },
    queue: [
      { index: 1, title: "Neon Skyline", uploader: "VYRON Demo", duration: 198, thumbnail: "" },
      { index: 2, title: "Slow Motion", uploader: "VYRON Demo", duration: 241, thumbnail: "" },
      { index: 3, title: "Afterglow", uploader: "VYRON Demo", duration: 167, thumbnail: "" },
    ],
    settings: { volume: 100, loop: "off", autoplay: true, always_on: false },
    favorites: [{ id: "1", title: "Saved track", uploader: "VYRON Demo", duration: 180 }],
  };

  async function refresh() {
    let payload;
    try {
      payload = await api("/api/state");
    } catch (error) {
      if (state.preview) {
        payload = demo;
      } else {
        toast(error.message === "unauthorized" ? "Open this app from Telegram" : "Connection lost");
        return;
      }
    }
    state.data = payload;
    renderNow(payload.now, payload.settings);
    renderQueue(payload.queue || []);
    renderSettings(payload.settings || {});
    renderFavorites(payload.favorites || []);
    $("chat-name").textContent = payload.chat?.title || "Player";
    $("app-version").textContent = payload.version || "–";
    $("app-streaming").textContent = payload.streaming ? "connected" : "file mode";
  }

  // ── interactions ────────────────────────────────────────────────────────
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tab = button.dataset.tab;
      document.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("active", b === button));
      document.querySelectorAll(".tab-panel").forEach((panel) =>
        panel.classList.toggle("active", panel.id === `tab-${state.tab}`));
      haptic("soft");
      if (state.tab === "queue" || state.tab === "settings") refresh();
    });
  });

  document.querySelectorAll(".transport [data-action], .quick-actions [data-action], .section-head [data-action]")
    .forEach((button) => {
      button.addEventListener("click", async () => {
        const action = button.dataset.action;
        if (action === "skipBack") {
          await act("seek", 0);
          return;
        }
        if (action === "loop") {
          const order = ["off", "one", "all"];
          const current = state.data?.settings?.loop || "off";
          await act("loop", order[(order.indexOf(current) + 1) % 3]);
          return;
        }
        if (action === "favorite") {
          const result = await act("favorite");
          toast(result?.saved ? "Saved to favourites ♥" : "Already saved");
          return;
        }
        await act(action);
      });
    });

  $("seek").addEventListener("pointerdown", () => { state.dragging = true; });
  $("seek").addEventListener("input", (event) => {
    const percent = Number(event.target.value);
    event.target.style.setProperty("--p", `${percent}%`);
    const total = state.data?.now?.duration || 0;
    $("time-elapsed").textContent = fmt((percent / 100) * total);
  });
  $("seek").addEventListener("change", async (event) => {
    state.dragging = false;
    const total = state.data?.now?.duration || 0;
    const target = Math.round((Number(event.target.value) / 100) * total);
    await act("seek", target);
  });

  let volumeTimer = null;
  $("volume").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    event.target.style.setProperty("--p", `${(value / 200) * 100}%`);
    $("volume-value").textContent = `${value}%`;
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(() => act("volume", value), 320);
  });

  $("queue-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-queue]");
    if (!button) return;
    const index = Number(button.closest(".item").dataset.index);
    if (button.dataset.queue === "jump") await act("jump", index);
    else await act("remove", index);
  });

  $("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = $("search-input").value.trim();
    if (!query) return;
    if (state.preview) {
      renderResults([
        { title: `${query} — result 1`, uploader: "preview", duration: 201 },
        { title: `${query} — result 2`, uploader: "preview", duration: 188 },
      ]);
      toast("Preview mode — open in Telegram to play");
      return;
    }
    try {
      const result = await api("/api/action", { action: "search", value: query });
      renderResults(result.results || []);
    } catch (error) {
      toast(error.message || "Search failed");
    }
  });

  $("search-results").addEventListener("click", async (event) => {
    const item = event.target.closest(".item");
    if (!item) return;
    await act("play", item.dataset.query);
    toast("Playing…");
  });

  document.querySelector('[data-setting="autoplay"]').addEventListener("change", () => act("autoplay"));
  document.querySelector('[data-setting="always"]').addEventListener("change", () => act("always"));
  $("loop-select").addEventListener("change", (event) => act("loop", event.target.value));
  $("btn-refresh").addEventListener("click", () => { refresh(); haptic("soft"); });

  // ── boot ────────────────────────────────────────────────────────────────
  refresh();
  state.timer = setInterval(() => {
    if (document.visibilityState === "visible") refresh();
  }, 5000);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
})();
