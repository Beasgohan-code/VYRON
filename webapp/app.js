/* ═══════════════════════════════════════════════════════════════════════════
   VYRON Player — app logic
   Views: Home · Search · Library · Queue · Playlists · Rooms · Profile
   Data:   /api/state (polled) · /api/home · /api/rooms · /api/playlists
   ═══════════════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  // ── environment ──────────────────────────────────────────────────────────
  const tg = window.Telegram?.WebApp;
  const params = new URLSearchParams(location.search);
  const token = params.get("t") || localStorage.getItem("vyron:token") || "";
  if (params.get("t")) localStorage.setItem("vyron:token", params.get("t"));

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmt = (seconds) => {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h
      ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${m}:${String(s).padStart(2, "0")}`;
  };
  const totalTime = (tracks) => fmt((tracks || []).reduce((sum, t) => sum + (Number(t.duration) || 0), 0));

  const haptic = (style = "light") => {
    try { tg?.HapticFeedback?.impactOccurred(style); } catch (_) {}
  };

  // ── store ────────────────────────────────────────────────────────────────
  const store = {
    state: null,
    home: null,
    rooms: [],
    playlists: [],
    results: [],
    view: "home",
    searchFilter: "all",
    libFilter: "liked",
    selectedPlaylist: null,
    menuTrack: null,
    query: "",
    dragging: false,
    homeLoaded: false,
    roomsLoaded: false,
    recent: JSON.parse(localStorage.getItem("vyron:recent") || "[]"),
    ui: {
      theme: localStorage.getItem("vyron:theme") || "beat",
      accent: localStorage.getItem("vyron:accent") || "violet",
      normalise: localStorage.getItem("vyron:normalise") === "1",
    },
  };

  const EFFECTS = [
    ["bass", "Bass"], ["treble", "Treble"], ["loud", "Loudness"],
    ["nightcore", "Nightcore"], ["vaporwave", "Vaporwave"], ["8d", "8D"],
    ["echo", "Echo"], ["karaoke", "Karaoke"], ["mono", "Mono"],
    ["speed", "2×"], ["slow", "0.5×"],
  ];

  // ── api ──────────────────────────────────────────────────────────────────
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

  let toastTimer = null;
  function toast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
  }

  // ── theme ────────────────────────────────────────────────────────────────
  function applyTheme() {
    document.documentElement.dataset.theme = store.ui.theme;
    document.documentElement.dataset.accent = store.ui.accent;
    $$(".theme-card").forEach((card) => card.classList.toggle("active", card.dataset.theme === store.ui.theme));
    $$(".accent-dot").forEach((dot) => dot.classList.toggle("active", dot.dataset.accent === store.ui.accent));
    try {
      tg?.setHeaderColor?.(store.ui.theme === "system" ? "#08080e" : "#08080e");
      tg?.setBackgroundColor?.("#08080e");
    } catch (_) {}
  }

  // ── actions ──────────────────────────────────────────────────────────────
  async function act(action, value) {
    haptic();
    try {
      const result = await api("/api/action", { action, value });
      if (result.preview) {
        toast("Preview mode — open in Telegram to control playback");
        return null;
      }
      await refreshState();
      return result;
    } catch (error) {
      toast(error.message || "Action failed");
      return null;
    }
  }

  async function play(query, mode = "play") {
    if (!query) return;
    toast(mode === "play_now" ? "Starting…" : "Adding to queue…");
    await act(mode, query);
  }

  async function addToPlaylist(track) {
    if (!store.playlists.length) {
      const created = await createPlaylist("My playlist");
      if (!created) return;
    }
    openModal(
      "Add to playlist",
      `<div class="rows" id="playlist-picker">${store.playlists
        .map(
          (pl) => `<li data-pick="${esc(pl.id)}"><span class="rk">≡</span>
            <span class="tx"><b>${esc(pl.name)}</b><span>${pl.count} tracks</span></span></li>`
        )
        .join("")}</div>`
    );
    $("#playlist-picker")?.addEventListener("click", async (event) => {
      const row = event.target.closest("[data-pick]");
      if (!row) return;
      const result = await act("playlist_add", { playlist_id: row.dataset.pick, track });
      toast(result?.added ? "Added to playlist" : "Already in that playlist");
      closeModal();
      await loadPlaylists();
    });
  }

  async function createPlaylist(name) {
    const clean = (name || "").trim();
    if (!clean) return null;
    const result = await act("playlist_create", clean);
    if (!result) return null;
    await loadPlaylists();
    toast(`Playlist “${clean}” created`);
    return result.playlist;
  }

  // ── modal ────────────────────────────────────────────────────────────────
  function openModal(title, body) {
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = body;
    $("#modal").hidden = false;
    haptic("soft");
  }
  function closeModal() {
    $("#modal").hidden = true;
  }

  function openDownload(prefill = "", kind = "audio") {
    openModal(
      "Download",
      `<form id="modal-download" class="modal-form">
        <label class="field-label">Link or search</label>
        <input id="modal-download-input" type="text" value="${esc(prefill)}" placeholder="Paste a YouTube link or type a name…" />
        <label class="field-label">Format</label>
        <div class="quality-row">
          <label><input type="radio" name="kind" value="audio" ${kind === "audio" ? "checked" : ""} /> <span>MP3 · 320 kbps</span></label>
          <label><input type="radio" name="kind" value="video" ${kind === "video" ? "checked" : ""} /> <span>MP4 · 720p</span></label>
        </div>
        <p class="muted small">The bot sends the file to your chat — this window can stay open.</p>
        <button class="pill-btn accent wide" type="submit"><svg class="i"><use href="#i-download"/></svg>Download</button>
      </form>`
    );
    const form = $("#modal-download");
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("#modal-download-input");
      const kind = $('input[name="kind"]:checked')?.value || "audio";
      const query = input.value.trim();
      if (!query) return;
      const result = await act("download", { query, kind });
      if (result) {
        toast(`Download started · ${kind === "video" ? "MP4" : "MP3"}`);
        closeModal();
      }
    });
    setTimeout(() => $("#modal-download-input")?.focus(), 60);
  }

  // ── rendering: shared bits ───────────────────────────────────────────────
  // Offline previews and audio-only files have no artwork; map every track to
  // one of the ten procedural covers shipped with the app.
  const COVERS = Array.from(
    { length: 10 },
    (_, index) => `/app/static/assets/covers/${String(index + 1).padStart(2, "0")}.jpg`
  );

  function coverFor(track) {
    const seed = `${track?.title || ""}${track?.uploader || ""}`;
    let hash = 0;
    for (let index = 0; index < seed.length; index += 1) {
      hash = (hash * 31 + seed.charCodeAt(index)) | 0;
    }
    return COVERS[Math.abs(hash) % COVERS.length];
  }

  const coverImg = (track, cls = "") => {
    const fallback = coverFor(track);
    const src = track?.thumbnail || fallback;
    return `<img class="${cls}" src="${esc(src)}" alt="" loading="lazy"
      onerror="this.onerror=null;this.src='${fallback}'" />`;
  };

  function resultRow(track, { index = null, context = "search" } = {}) {
    const query = esc(track.query || `${track.title} ${track.uploader || ""}`);
    return `<li class="result" data-track='${esc(JSON.stringify(track))}'>
      ${index !== null ? `<span class="idx">${index}</span>` : ""}
      ${coverImg(track)}
      <div class="info">
        <b>${esc(track.title)}</b>
        <span>${esc(track.uploader || track.source || "unknown")}${track.duration ? ` · ${fmt(track.duration)}` : ""}</span>
      </div>
      <span class="dur">${fmt(track.duration)}</span>
      <div class="acts">
        <button class="mini-action play" data-action="play-now" data-query="${query}" aria-label="Play now"><svg class="i"><use href="#i-play"/></svg></button>
        <button class="mini-action" data-action="queue" data-query="${query}" aria-label="Add to queue"><svg class="i"><use href="#i-plus"/></svg></button>
        <button class="mini-action" data-action="track-menu" aria-label="More"><svg class="i"><use href="#i-more"/></svg></button>
      </div>
    </li>`;
  }

  function trackCard(track, { rank = null, mix = false, badge = "" } = {}) {
    const query = esc(track.query || `${track.title} ${track.uploader || ""}`);
    return `<article class="card-track ${mix ? "card-mix" : ""}" data-track='${esc(JSON.stringify(track))}'>
      <div class="cover">
        ${rank !== null ? `<span class="rank">${rank}</span>` : ""}
        ${coverImg(track)}
        ${badge ? `<span class="badge">${esc(badge)}</span>` : ""}
        <button class="hover-play" data-action="play-now" data-query="${query}" aria-label="Play"><svg class="i"><use href="#i-play"/></svg></button>
        <button class="mini-action add" data-action="track-menu" aria-label="More"><svg class="i"><use href="#i-more"/></svg></button>
      </div>
      <div class="t">${esc(track.title)}</div>
      <div class="s">${esc(track.uploader || track.source || "")}</div>
    </article>`;
  }

  const skeletons = (count = 6) =>
    Array.from({ length: count }, () => '<div class="skeleton-card"></div>').join("");

  // ── render: home ─────────────────────────────────────────────────────────
  function greeting() {
    const hour = new Date().getHours();
    if (hour < 5) return "Good night,";
    if (hour < 12) return "Good morning,";
    if (hour < 17) return "Good afternoon,";
    if (hour < 22) return "Good evening,";
    return "Good night,";
  }

  function renderHome() {
    const home = store.home;
    if (!home) return;
    const hero = home.hero || {};
    const heading = $("#greeting");
    if (heading) {
      heading.innerHTML = `${esc(greeting())}<br />${esc(hero.headline || "Music hits different here.")}`;
    }
    const heroArt = $(".hero-art");
    if (heroArt && hero.cover) {
      heroArt.style.backgroundImage = `linear-gradient(180deg, rgba(8,8,14,.2), rgba(8,8,14,.85)), url("${hero.cover}")`;
      heroArt.style.backgroundSize = "cover";
      heroArt.style.backgroundPosition = "center";
    }

    const trending = home.trending || [];
    const trendingShelf = $("#shelf-trending");
    if (trendingShelf) {
      trendingShelf.dataset.loading = "false";
      trendingShelf.innerHTML = trending.length
        ? trending.map((track, i) => trackCard(track, { rank: i + 1 })).join("")
        : '<p class="empty-state">Nothing trending right now.</p>';
    }

    const mixes = $("#shelf-mixes");
    const shelves = home.shelves || [];
    if (mixes) {
      mixes.dataset.loading = "false";
      mixes.innerHTML = shelves.length
        ? shelves
            .map((shelf) =>
              (shelf.tracks || [])
                .slice(0, 1)
                .map((track) => trackCard(track, { mix: true, badge: shelf.title }))
                .join("")
            )
            .join("")
        : '<p class="empty-state">Mixes are loading…</p>';
      $$(".card-mix", mixes).forEach((card, index) => {
        const shelf = shelves[index];
        if (shelf) card.dataset.shelf = shelf.key;
      });
    }

    const moods = $("#mood-chips");
    if (moods) {
      moods.innerHTML = (home.moods || [])
        .map((mood) => `<button class="chip" data-mood="${esc(mood.key)}">${esc(mood.title)}</button>`)
        .join("");
    }
  }

  function renderHomeHistory(state) {
    const list = $("#home-history");
    if (!list) return;
    const history = (state?.history || []).slice(0, 5);
    if (!history.length) {
      list.innerHTML = '<li class="empty-row">Nothing played yet — start with a mix above.</li>';
      return;
    }
    list.innerHTML = history
      .map(
        (track) => `<li data-query="${esc(track.query || track.title)}">
          ${coverImg(track)}
          <span class="tx"><b>${esc(track.title)}</b>
          <span>${esc(track.uploader || "unknown")} · ${fmt(track.duration)}</span></span>
          <svg class="i chev"><use href="#i-chevron"/></svg>
        </li>`
      )
      .join("");
    $$("#home-history li[data-query]").forEach((row) =>
      row.addEventListener("click", () => play(row.dataset.query, "play_now"))
    );
  }

  // ── render: state ────────────────────────────────────────────────────────
  function renderState() {
    const state = store.state;
    if (!state) return;
    const now = state.now;
    const settings = state.settings || {};

    // rail now-playing
    const cover = $("#np-cover");
    const fallback = $("#np-fallback");
    if (cover) {
      if (now) {
        cover.onerror = () => {
          cover.onerror = null;
          cover.src = coverFor(now);
        };
        cover.src = now.thumbnail || coverFor(now);
        cover.style.display = "block";
        if (fallback) fallback.style.display = "none";
      } else {
        cover.removeAttribute("src");
        cover.style.display = "none";
        if (fallback) fallback.style.display = "grid";
      }
    }
    $("#np-title").textContent = now?.title || "Nothing playing";
    $("#np-artist").textContent = now?.uploader || "Send /play in the chat";
    $("#np-source").textContent = now ? now.source || "youtube" : "idle";

    const playIcon = $("#np-play-icon");
    const useEl = playIcon?.querySelector("use");
    if (useEl) useEl.setAttribute("href", now && !now.paused ? "#i-pause" : "#i-play");

    const wave = $("#np-wave");
    if (wave) wave.classList.toggle("paused", !now || now.paused);

    const total = now?.duration || 0;
    const elapsed = now?.elapsed || 0;
    if (!store.dragging) {
      const percent = total ? Math.min(100, (elapsed / total) * 100) : 0;
      const seek = $("#np-seek");
      if (seek) {
        seek.value = Math.round(percent * 10);
        seek.style.setProperty("--p", `${percent}%`);
        seek.disabled = !total;
      }
      $("#np-elapsed").textContent = fmt(elapsed);
      $("#np-total").textContent = total ? fmt(total) : "live";
    }

    // mobile mini player
    const mini = $("#mini-player");
    if (mini) {
      mini.hidden = !now;
      if (now) {
        const miniCover = $("#mini-cover");
        if (miniCover) {
          miniCover.onerror = () => {
            miniCover.onerror = null;
            miniCover.src = coverFor(now);
          };
          miniCover.src = now.thumbnail || coverFor(now);
        }
        $("#mini-title").textContent = now.title;
        $("#mini-artist").textContent = `${now.uploader || ""} ${now.paused ? "· paused" : ""}`.trim();
      }
    }

    // queue
    renderQueue(state);
    renderHomeHistory(state);
    // library + profile reflect state
    renderLibrary();
    renderProfileChrome(state);
    renderEffects(settings.effects || []);
  }

  function renderQueue(state) {
    const queue = state?.queue || [];
    const now = state?.now;
    const list = $("#queue-list");
    if (!list) return;
    const rows = [];
    if (now) rows.push(`<li class="q-item playing">
        <span class="idx">▸</span>
        ${coverImg(now)}
        <div class="info"><b>${esc(now.title)}</b><span>${esc(now.uploader || "")} · playing</span></div>
        <span class="dur">${fmt(now.elapsed)} / ${fmt(now.duration)}</span>
      </li>`);
    queue.forEach((track) => {
      rows.push(`<li class="q-item" data-track='${esc(JSON.stringify(track))}'>
        <span class="idx">${track.index}</span>
        ${coverImg(track)}
        <div class="info"><b>${esc(track.title)}</b><span>${esc(track.uploader || "")}</span></div>
        <span class="dur">${fmt(track.duration)}</span>
        <button class="mini-action" data-action="jump" data-index="${track.index}" aria-label="Play now"><svg class="i"><use href="#i-play"/></svg></button>
        <button class="mini-action" data-action="remove" data-index="${track.index}" aria-label="Remove"><svg class="i"><use href="#i-close"/></svg></button>
      </li>`);
    });
    list.innerHTML = rows.join("");
    $("#queue-empty").hidden = rows.length > 0;
    $("#queue-sub").textContent = queue.length
      ? `${queue.length} tracks · ${totalTime(queue)}`
      : now
      ? "Nothing queued after this track"
      : "Nothing queued";
    const autoplay = $("#queue-autoplay");
    if (autoplay && state?.settings) autoplay.checked = Boolean(state.settings.autoplay);
  }

  // ── render: library ──────────────────────────────────────────────────────
  function renderLibrary() {
    const state = store.state;
    if (!state) return;
    const favorites = state.favorites || [];
    const history = state.history || [];
    const playlists = state.playlists || [];

    $("#liked-count").textContent = `${favorites.length} track${favorites.length === 1 ? "" : "s"}`;
    $("#lib-stats").innerHTML = `
      <div><b>${favorites.length}</b><span>liked</span></div>
      <div><b>${playlists.length}</b><span>playlists</span></div>
      <div><b>${history.length}</b><span>played</span></div>`;

    const list = $("#library-list");
    const filter = store.libFilter;
    let rows = [];
    if (filter === "liked") rows = favorites;
    else if (filter === "history") rows = history;
    else {
      list.innerHTML = playlists.length
        ? playlists
            .map(
              (pl) => `<li class="result" data-playlist="${esc(pl.id)}">
                <div class="ph"><svg class="i"><use href="#i-playlist"/></svg></div>
                <div class="info"><b>${esc(pl.name)}</b><span>${pl.count} tracks · ${fmt(pl.duration)}</span></div>
                <div class="acts"><button class="mini-action play" aria-label="Play"><svg class="i"><use href="#i-play"/></svg></button></div>
              </li>`
            )
            .join("")
        : "";
      $("#library-empty").hidden = playlists.length > 0;
      $("#liked-card").hidden = true;
      return;
    }

    list.innerHTML = rows.map((track, i) => resultRow(track, { index: i + 1 })).join("");
    $("#library-empty").hidden = rows.length > 0;
    $("#liked-card").hidden = filter !== "liked";
  }

  // ── render: playlists ────────────────────────────────────────────────────
  function renderPlaylists() {
    const grid = $("#playlist-grid");
    const list = store.playlists || [];
    $("#playlists-sub").textContent = list.length
      ? `${list.length} playlist${list.length === 1 ? "" : "s"}`
      : "Your saved collections";
    grid.innerHTML = list
      .map(
        (pl) => `<button class="playlist-card" data-playlist="${esc(pl.id)}">
          <div class="covers">${
            pl.covers && pl.covers.length
              ? Array.from({ length: 4 }, (_, i) =>
                  pl.covers[i]
                    ? `<img src="${esc(pl.covers[i])}" alt="" loading="lazy" />`
                    : '<span class="ph"></span>'
                ).join("")
              : '<span class="ph"></span><span class="ph"></span><span class="ph"></span><span class="ph"></span>'
          }</div>
          <b>${esc(pl.name)}</b>
          <span>${pl.count} tracks · ${fmt(pl.duration)}</span>
        </button>`
      )
      .join("");
    $("#playlist-empty").hidden = list.length > 0;
  }

  function renderPlaylistDetail(playlist) {
    const panel = $("#playlist-detail");
    if (!playlist) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    $("#playlist-title").textContent = `${playlist.name} · ${playlist.count} tracks`;
    $("#playlist-tracks").innerHTML = (playlist.tracks || []).length
      ? playlist.tracks.map((track, i) => resultRow(track, { index: i + 1 })).join("")
      : '<li class="empty-row">This playlist is empty.</li>';
    $("#playlist-play").dataset.playlist = playlist.id;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ── render: rooms ────────────────────────────────────────────────────────
  function renderRooms() {
    const list = $("#rooms-list");
    const rooms = store.rooms || [];
    $("#rooms-count").textContent = rooms.length ? `${rooms.length} live` : "";
    list.innerHTML = rooms
      .map(
        (room) => `<li class="room-card">
          ${room.track?.thumbnail ? `<img src="${esc(room.track.thumbnail)}" alt="" loading="lazy" />` : '<div class="ph"></div>'}
          <div class="info">
            <b>${esc(room.title)}</b>
            <span>${room.playing && !room.paused ? '<span class="live"><i></i>live</span>' : "paused"} · ${room.listeners} listening</span>
            <span>${esc(room.track?.title || "nothing playing")}</span>
          </div>
          ${
            room.username
              ? `<a class="mini-action play" href="https://t.me/${esc(room.username)}" target="_blank" rel="noopener" aria-label="Open chat"><svg class="i"><use href="#i-chevron"/></svg></a>`
              : `<button class="mini-action" data-action="open-chat" data-chat="${room.chat_id}" aria-label="Open chat"><svg class="i"><use href="#i-chevron"/></svg></button>`
          }
        </li>`
      )
      .join("");

    const empty = $("#rooms-empty");
    if (empty) empty.hidden = rooms.length > 0;

    const mini = $("#rooms-mini");
    if (mini) {
      mini.innerHTML = rooms.length
        ? rooms
            .slice(0, 3)
            .map(
              (room) => `<li data-view="rooms">
                <span class="rk">${room.playing && !room.paused ? "🔊" : "⏸"}</span>
                <span class="tx"><b>${esc(room.title)}</b><span>${room.listeners} listening</span></span>
              </li>`
            )
            .join("")
        : '<li class="empty-row">No active rooms yet.</li>';
    }
  }

  // ── render: search ───────────────────────────────────────────────────────
  function renderResults() {
    const list = $("#search-results");
    const filter = store.searchFilter;
    let tracks = store.results || [];
    if (filter === "artists") {
      const seen = new Map();
      tracks.forEach((track) => {
        const key = track.uploader || "unknown";
        if (!seen.has(key)) seen.set(key, { ...track, title: key, uploader: `${tracks.filter((t) => t.uploader === key).length} songs` });
      });
      tracks = Array.from(seen.values());
    }
    if (filter === "playlists") {
      const matches = (store.playlists || []).filter((pl) =>
        pl.name.toLowerCase().includes((store.query || "").toLowerCase())
      );
      list.innerHTML = matches
        .map(
          (pl) => `<li class="result" data-playlist="${esc(pl.id)}">
            <div class="ph"><svg class="i"><use href="#i-playlist"/></svg></div>
            <div class="info"><b>${esc(pl.name)}</b><span>${pl.count} tracks</span></div>
            <div class="acts"><button class="mini-action play"><svg class="i"><use href="#i-play"/></svg></button></div>
          </li>`
        )
        .join("");
      $("#search-empty").hidden = matches.length > 0;
      return;
    }
    list.innerHTML = tracks.map((track, i) => resultRow(track, { index: i + 1 })).join("");
    $("#search-empty").hidden = tracks.length > 0;
  }

  function renderRecentSearches() {
    const row = $("#recent-searches");
    const head = $("#recent-head");
    if (!row) return;
    head.hidden = store.recent.length === 0;
    row.innerHTML = store.recent
      .map((term) => `<button class="chip" data-term="${esc(term)}">${esc(term)}</button>`)
      .join("");
  }

  // ── render: profile / settings ───────────────────────────────────────────
  function renderProfileChrome(state) {
    const user = state?.user || {};
    const name = user.name || "Listener";
    const initials = (name || "V").slice(0, 1).toUpperCase();
    $("#profile-avatar").textContent = initials;
    $("#top-avatar").textContent = initials;
    $("#side-avatar").textContent = initials;
    $("#profile-name").textContent = name;
    $("#profile-handle").textContent = user.username ? `@${user.username}` : `id ${user.id || "–"}`;
    $("#profile-chat").textContent = state?.chat?.title || "private chat";
    $("#side-name").textContent = name;
    $("#side-handle").textContent = user.username ? `@${user.username}` : "VYRON";
    const listeners = state?.stats?.chats;
    $("#side-listeners").textContent = listeners ? `Online · ${listeners} chats` : "Online";

    $("#integ-bot").textContent = `@${state?.bot || "VyronMusicBot"}`;
    $("#integ-stream").textContent = state?.streaming ? "connected" : "file mode";
    $("#integ-chat").textContent = state?.chat?.title || "private";
    $("#integ-version").textContent = state?.version || "–";

    const settings = state?.settings || {};
    const autoplay = $('[data-setting="autoplay"]');
    if (autoplay) autoplay.checked = Boolean(settings.autoplay);
    const always = $('[data-setting="always"]');
    if (always) always.checked = Boolean(settings.always_on);
    const loop = $("#loop-select");
    if (loop && settings.loop) loop.value = settings.loop;
    const normalise = $('[data-ui="normalise"]');
    if (normalise) normalise.checked = store.ui.normalise;
    const volume = $("#volume-slider");
    if (volume && document.activeElement !== volume) {
      volume.value = settings.volume || 100;
      volume.style.setProperty("--p", `${((settings.volume || 100) / 200) * 100}%`);
    }
  }

  function renderEffects(active) {
    const row = $("#effects-chips");
    if (!row) return;
    row.innerHTML = EFFECTS.map(
      ([key, label]) =>
        `<button class="chip fx ${active.includes(key) ? "active" : ""}" data-effect="${key}">${label}</button>`
    ).join("");
  }

  // ── loading ──────────────────────────────────────────────────────────────
  async function refreshState() {
    try {
      const state = await api("/api/state");
      store.state = state;
      renderState();
    } catch (error) {
      if (error.message !== "unauthorized") toast(error.message || "Connection lost");
    }
  }

  async function loadHome(force = false) {
    if (store.homeLoaded && !force) return;
    try {
      store.home = await api("/api/home");
      store.homeLoaded = true;
      renderHome();
    } catch (error) {
      toast(error.message || "Could not load discovery");
      $("#shelf-trending").innerHTML = '<p class="empty-state">Discovery unavailable — try again in a moment.</p>';
      $("#shelf-mixes").innerHTML = "";
    }
  }

  async function loadRooms() {
    try {
      const payload = await api("/api/rooms");
      store.rooms = payload.rooms || [];
      renderRooms();
    } catch (_) {}
  }

  async function loadPlaylists() {
    try {
      const payload = await api("/api/playlists");
      store.playlists = payload.playlists || [];
      renderPlaylists();
      if (store.selectedPlaylist) {
        const refreshed = store.playlists.find((pl) => pl.id === store.selectedPlaylist.id);
        if (refreshed) renderPlaylistDetail(refreshed);
      }
    } catch (_) {}
  }

  async function runSearch(query, { remember = true } = {}) {
    const clean = (query || "").trim();
    if (!clean) return;
    store.query = clean;
    $("#search-input").value = clean;
    if (remember) {
      store.recent = [clean, ...store.recent.filter((item) => item !== clean)].slice(0, 8);
      localStorage.setItem("vyron:recent", JSON.stringify(store.recent));
      renderRecentSearches();
    }
    try {
      const payload = await api("/api/search", { query: clean, limit: 12 });
      store.results = payload.results || [];
      renderResults();
    } catch (error) {
      toast(error.message || "Search failed");
    }
  }

  // ── navigation ───────────────────────────────────────────────────────────
  function showView(name) {
    store.view = name;
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    $$("[data-view]").forEach((item) => {
      if (item.classList.contains("nav-item") || item.classList.contains("tab-item")) {
        item.classList.toggle("active", item.dataset.view === name);
      }
    });
    haptic("soft");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (name === "home") loadHome();
    if (name === "rooms") loadRooms();
    if (name === "playlists") loadPlaylists();
    if (name === "library") renderLibrary();
    if (name === "profile") renderProfileChrome(store.state);
    if (name === "search") setTimeout(() => $("#search-input")?.focus(), 120);
  }

  // ── events ───────────────────────────────────────────────────────────────
  document.addEventListener("click", async (event) => {
    const viewBtn = event.target.closest("[data-view]");
    if (viewBtn && !viewBtn.closest(".result")) {
      showView(viewBtn.dataset.view);
      if (viewBtn.dataset.focus === "trending") $("#global-query")?.focus();
      return;
    }

    const themeBtn = event.target.closest("[data-theme]");
    if (themeBtn) {
      store.ui.theme = themeBtn.dataset.theme;
      localStorage.setItem("vyron:theme", store.ui.theme);
      applyTheme();
      $("#theme-hint").textContent =
        store.ui.theme === "telegram"
          ? "Colours follow Telegram — change your Telegram theme and this follows."
          : store.ui.theme === "system"
          ? "Follows your device light/dark setting."
          : "Beat — VYRON's signature violet edition.";
      return;
    }

    const accentBtn = event.target.closest("[data-accent]");
    if (accentBtn) {
      store.ui.accent = accentBtn.dataset.accent;
      localStorage.setItem("vyron:accent", store.ui.accent);
      applyTheme();
      return;
    }

    const effectBtn = event.target.closest("[data-effect]");
    if (effectBtn) {
      const current = store.state?.settings?.effects || [];
      const key = effectBtn.dataset.effect;
      const next = current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key].slice(0, 3);
      const result = await act("effects", next);
      if (result) toast(`Effects: ${result.labels || "off"}`);
      return;
    }

    const playlistCard = event.target.closest("[data-playlist]");
    if (playlistCard) {
      const playlist = store.playlists.find((pl) => pl.id === playlistCard.dataset.playlist);
      if (playlist) {
        store.selectedPlaylist = playlist;
        showView("playlists");
        renderPlaylistDetail(playlist);
      }
      return;
    }

    const mood = event.target.closest("[data-mood]");
    if (mood) {
      const key = mood.dataset.mood;
      toast(`Loading ${key}…`);
      try {
        const payload = await api(`/api/mix?key=${encodeURIComponent(key)}`);
        store.results = payload.tracks || [];
        showView("search");
        store.searchFilter = "all";
        store.query = key;
        $("#search-input").value = key;
        renderResults();
      } catch (error) {
        toast(error.message || "Could not load that mix");
      }
      return;
    }

    const term = event.target.closest("[data-term]");
    if (term) {
      runSearch(term.dataset.term, { remember: false });
      return;
    }

    const filterTab = event.target.closest(".tab[data-filter]");
    if (filterTab) {
      const group = filterTab.closest(".tabs").id;
      Array.from(filterTab.parentElement.children).forEach((tab) => tab.classList.toggle("active", tab === filterTab));
      if (group === "search-tabs") {
        store.searchFilter = filterTab.dataset.filter;
        renderResults();
      } else {
        store.libFilter = filterTab.dataset.filter;
        renderLibrary();
      }
      return;
    }

    const menuItem = event.target.closest("[data-menu]");
    if (menuItem) {
      const payload = store.menuTrack;
      const kind = menuItem.dataset.menu;
      closeModal();
      if (!payload) return;
      if (kind === "play") return play(payload.query, "play_now");
      if (kind === "queue") return play(payload.query, "play");
      if (kind === "like") {
        const result = await act("favorite_track", payload);
        return toast(result?.saved ? "Added to liked songs" : "Already liked");
      }
      if (kind === "playlist") return addToPlaylist(payload);
      if (kind === "download") return openDownload(payload.query);
      return;
    }

    const openEl = event.target.closest("[data-open]");
    if (openEl) {
      if (openEl.dataset.open === "download") openDownload("");
      return;
    }

    const actionEl = event.target.closest("[data-action]");
    if (actionEl) {
      event.preventDefault();
      const action = actionEl.dataset.action;
      const query = actionEl.dataset.query;
      const track = actionEl.closest("[data-track]")?.dataset.track;

      if (action === "play-now") return play(query, "play_now");
      if (action === "queue") return play(query, "play");
      if (action === "jump") return act("jump", Number(actionEl.dataset.index));
      if (action === "remove") return act("remove", Number(actionEl.dataset.index));
      if (action === "toggle") return act("toggle");
      if (action === "skip") return act("skip", 1);
      if (action === "loop") {
        const order = ["off", "one", "all"];
        const current = store.state?.settings?.loop || "off";
        const next = order[(order.indexOf(current) + 1) % 3];
        const result = await act("loop", next);
        if (result) toast(`Loop: ${result.loop}`);
        return;
      }
      if (action === "favorite") {
        const result = await act("favorite");
        toast(result?.saved ? "Saved to liked songs ♥" : "Already in liked songs");
        return;
      }
      if (action === "shuffle") {
        const result = await act("shuffle");
        if (result) toast(`Shuffled ${result.shuffled || 0} tracks`);
        return;
      }
      if (action === "clear") {
        const result = await act("clear");
        if (result) toast(`Cleared ${result.removed || 0} tracks`);
        return;
      }
      if (action === "refresh-rooms") {
        await loadRooms();
        toast("Rooms refreshed");
        return;
      }
      if (action === "open-chat") {
        toast("Open this room in Telegram to join the voice chat");
        return;
      }
      if (action === "play-liked") {
        const liked = store.state?.favorites || [];
        if (!liked.length) return toast("No liked songs yet");
        toast(`Queuing ${liked.length} liked songs…`);
        for (const item of liked.slice(0, 25)) {
          await api("/api/action", { action: "play", value: item.query || `${item.title} ${item.uploader || ""}` }).catch(() => null);
        }
        await refreshState();
        toast("Liked songs queued");
        return;
      }
      if (action === "track-menu") {
        let payload = null;
        try { payload = track ? JSON.parse(track) : null; } catch (_) {}
        if (!payload) return;
        store.menuTrack = payload;
        openModal(
          "Track",
          `<p class="muted small">${esc(payload.title)}</p>
           <div class="rows">
             <li data-menu="play"><span class="rk">▸</span><span class="tx"><b>Play now</b></span></li>
             <li data-menu="queue"><span class="rk">+</span><span class="tx"><b>Add to queue</b></span></li>
             <li data-menu="like"><span class="rk">♥</span><span class="tx"><b>Add to liked songs</b></span></li>
             <li data-menu="playlist"><span class="rk">≡</span><span class="tx"><b>Add to playlist</b></span></li>
             <li data-menu="download"><span class="rk">⤓</span><span class="tx"><b>Download</b></span></li>
           </div>`
        );
        return;
      }
      return;
    }

    // clicking a result row body plays it
    const row = event.target.closest(".result[data-track]");
    if (row) {
      try {
        const payload = JSON.parse(row.dataset.track);
        play(payload.query, "play_now");
      } catch (_) {}
    }
  });

  // forms
  $("#search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch($("#search-input").value);
  });
  $("#search-input")?.addEventListener("input", (event) => {
    $("#search-clear").hidden = !event.target.value;
  });
  $("#search-clear")?.addEventListener("click", () => {
    $("#search-input").value = "";
    $("#search-clear").hidden = true;
    $("#search-input").focus();
  });
  $("#global-search")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = $("#global-query").value.trim();
    if (!query) return;
    store.homeLoaded = true; // avoid clobbering
    showView("search");
    runSearch(query);
  });
  $("#mini-search")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = $("#mini-query").value.trim();
    if (!query) return;
    try {
      const payload = await api("/api/search", { query, limit: 6 });
      const list = $("#mini-results");
      list.innerHTML = (payload.results || [])
        .map(
          (track) => `<li data-query="${esc(track.query)}">
            <span class="rk">▸</span>
            <span class="tx"><b>${esc(track.title)}</b><span>${fmt(track.duration)}</span></span>
          </li>`
        )
        .join("");
      $$("#mini-results li[data-query]").forEach((row) =>
        row.addEventListener("click", () => play(row.dataset.query, "play_now"))
      );
    } catch (error) {
      toast(error.message || "Search failed");
    }
  });
  $("#download-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const kind = $('#quality-row input[name="quality"]:checked')?.value || "audio";
    openDownload($("#download-input").value.trim(), kind);
  });
  $("#playlist-new")?.addEventListener("click", () => {
    openModal(
      "New playlist",
      `<form id="new-playlist" class="modal-form">
        <label class="field-label">Name</label>
        <input id="new-playlist-name" type="text" placeholder="Late night drive" />
        <button class="pill-btn accent wide" type="submit">Create playlist</button>
      </form>`
    );
    $("#new-playlist")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = $("#new-playlist-name").value.trim();
      if (!name) return;
      await createPlaylist(name);
      closeModal();
    });
    setTimeout(() => $("#new-playlist-name")?.focus(), 60);
  });
  $("#lib-new")?.addEventListener("click", () => $("#playlist-new").click());
  $("#lib-export")?.addEventListener("click", () => {
    const payload = {
      exported: new Date().toISOString(),
      favorites: store.state?.favorites || [],
      history: store.state?.history || [],
      playlists: store.playlists || [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "vyron-library.json";
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Library exported");
  });
  $("#playlist-play")?.addEventListener("click", async (event) => {
    const id = event.currentTarget.dataset.playlist;
    if (!id) return;
    const result = await act("playlist_play", id);
    if (result) toast(`Queued ${result.queued} tracks from “${result.name}”`);
  });
  $("#playlist-close")?.addEventListener("click", () => {
    store.selectedPlaylist = null;
    $("#playlist-detail").hidden = true;
  });

  // settings controls
  $$('[data-setting]').forEach((input) =>
    input.addEventListener("change", async () => {
      const key = input.dataset.setting;
      const result = await act(key === "always" ? "always" : "autoplay");
      if (result) toast("Saved");
    })
  );
  $("#loop-select")?.addEventListener("change", (event) => act("loop", event.target.value));
  $('[data-ui="normalise"]')?.addEventListener("change", (event) => {
    store.ui.normalise = event.target.checked;
    localStorage.setItem("vyron:normalise", store.ui.normalise ? "1" : "0");
    toast("Preference saved");
  });
  $("#queue-autoplay")?.addEventListener("change", () => act("autoplay"));

  // seek + volume
  const seek = $("#np-seek");
  seek?.addEventListener("pointerdown", () => { store.dragging = true; });
  seek?.addEventListener("input", (event) => {
    const percent = Number(event.target.value) / 10;
    event.target.style.setProperty("--p", `${percent}%`);
    const total = store.state?.now?.duration || 0;
    $("#np-elapsed").textContent = fmt((percent / 100) * total);
  });
  seek?.addEventListener("change", async (event) => {
    store.dragging = false;
    const total = store.state?.now?.duration || 0;
    await act("seek", Math.round((Number(event.target.value) / 1000) * total));
  });

  let volumeTimer = null;
  $("#volume-slider")?.addEventListener("input", (event) => {
    const value = Number(event.target.value);
    event.target.style.setProperty("--p", `${(value / 200) * 100}%`);
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(() => act("volume", value), 320);
  });

  $("#btn-fullscreen")?.addEventListener("click", () => {
    if (tg?.requestFullscreen) tg.requestFullscreen();
    else if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
    else document.exitFullscreen?.();
  });
  $("#btn-logout")?.addEventListener("click", () => {
    localStorage.removeItem("vyron:recent");
    localStorage.removeItem("vyron:normalise");
    toast("Local data cleared");
  });
  $("#modal-close")?.addEventListener("click", closeModal);
  $("#modal")?.addEventListener("click", (event) => {
    if (event.target.id === "modal") closeModal();
  });
  $("#btn-bell")?.addEventListener("click", () => toast("No new notifications"));
  $("#side-send")?.addEventListener("click", () => {
    const url = "https://t.me/VyronMusicBot";
    if (tg?.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, "_blank", "noopener");
  });
  $("#nav-bot")?.addEventListener("click", (event) => {
    if (tg?.openTelegramLink) {
      event.preventDefault();
      tg.openTelegramLink("https://t.me/VyronMusicBot");
    }
  });

  // keyboard
  document.addEventListener("keydown", (event) => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (event.key === "Escape") return closeModal();
    if (typing) return;
    if (event.key === "/") { event.preventDefault(); $("#global-query")?.focus(); }
    if (event.code === "Space") { event.preventDefault(); act("toggle"); }
    if (event.key.toLowerCase() === "n") act("skip", 1);
  });

  // ── boot ─────────────────────────────────────────────────────────────────
  function buildWave() {
    const wave = $("#np-wave");
    if (!wave) return;
    wave.innerHTML = Array.from({ length: 26 }, () => {
      const height = 25 + Math.random() * 75;
      const delay = Math.random() * 0.9;
      return `<i style="height:${height}%;animation-delay:${delay}s"></i>`;
    }).join("");
  }

  async function boot() {
    buildWave();
    applyTheme();
    renderRecentSearches();
    if (tg) {
      tg.ready();
      tg.expand();
      try { tg.setHeaderColor("#08080e"); tg.setBackgroundColor("#08080e"); } catch (_) {}
    }
    $("#shelf-trending").innerHTML = skeletons(6);
    $("#shelf-mixes").innerHTML = skeletons(5);

    await Promise.allSettled([refreshState(), loadHome(), loadRooms(), loadPlaylists()]);

    setInterval(() => {
      if (document.visibilityState === "visible") refreshState();
    }, 5000);
    setInterval(() => {
      if (document.visibilityState === "visible" && ["home", "rooms"].includes(store.view)) loadRooms();
    }, 45000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        refreshState();
        if (store.view === "rooms") loadRooms();
      }
    });
  }

  boot();
})();
