import { Clock3, Download, Headphones, Play, Plus, RefreshCw, Search, Sparkles, Users, Zap } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { coverFor, fmtDuration, greeting } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { Panel, SectionHead } from "../components/Panel";
import { TrackCard } from "../components/TrackCard";
import { Equalizer } from "../components/Equalizer";
import { Aurora } from "../components/Aurora";
import { Count } from "../components/Count";
import { useTilt } from "../lib/anim";

export function HomeView() {
  const {
    home,
    state,
    play,
    loadMix,
    setView,
    runSearch,
    openModal,
    rooms,
    refreshRooms,
    playlists,
    act,
    toast,
    audio,
  } = useApp();
  const [miniQuery, setMiniQuery] = useState("");
  const [miniResults, setMiniResults] = useState<{ title: string; duration?: number; query?: string }[]>([]);
  const [downloadQuery, setDownloadQuery] = useState("");
  const [quality, setQuality] = useState<"audio" | "video">("audio");
  const artRef = useTilt<HTMLDivElement>(6);

  const trending = home?.trending ?? [];
  const shelves = home?.shelves ?? [];
  const moods = home?.moods ?? [];
  const history = (state?.history ?? []).slice(0, 5);

  return (
    <section className="view active">
      <div className="hero">
        <Aurora className="hero-aurora" tone="violet" />
        <div className="hero-copy">
          <span className="eyebrow">
            <Sparkles size={13} /> your listening room
          </span>
          <h1>
            {greeting()}
            <br />
            {home?.hero.headline ?? "Music hits different here."}
          </h1>
          <p>{home?.hero.subline ?? "Discover, stream, download and listen together — all in one place."}</p>
          <div className="hero-actions">
            {audio.track ? (
              <button type="button" className="pill-btn accent" onClick={() => audio.setExpanded(true)}>
                <Equalizer playing={audio.playing} bars={4} /> Resume “{audio.track.title.slice(0, 18)}”
              </button>
            ) : (
              <button type="button" className="pill-btn accent" onClick={() => void play(trending[0]?.query, "play_now")}>
                <Play size={15} fill="currentColor" /> Surprise me
              </button>
            )}
            <button type="button" className="pill-btn" onClick={() => setView("search")}>
              <Search size={15} /> Search
            </button>
            <button type="button" className="pill-btn" onClick={() => openModal({ type: "download" })}>
              <Download size={15} /> Download
            </button>
            <button type="button" className="pill-btn" onClick={() => setView("rooms")}>
              <Users size={15} /> Listen together
            </button>
          </div>
          <div className="hero-stats">
            <span>
              <Count value={state?.favorites?.length ?? 0} /> liked
            </span>
            <span>
              <Count value={playlists.length} /> playlists
            </span>
            <span>
              <Count value={rooms.length} /> live rooms
            </span>
          </div>
        </div>
        <div
          ref={artRef}
          className="hero-art"
          style={{ backgroundImage: `url("${home?.hero.cover || coverFor({ title: "vyron" })}")` }}
          aria-hidden="true"
        >

          <span className="hero-note">
            <Zap size={14} /> voice-chat streaming · file fallback
          </span>
        </div>
      </div>

      {history.length > 0 && (
        <>
          <SectionHead right={<span className="muted small">on this device</span>}>
            <span className="flame">
              <Clock3 size={15} /> Continue listening
            </span>
          </SectionHead>
          <div className="continue-row">
            {history.map((track, index) => (
              <button
                key={`${track.id ?? track.title}-${index}`}
                type="button"
                className={`continue-card ${audio.isCurrent(track) ? "current" : ""}`}
                onClick={() => void play(track, "play_now")}
                aria-label={`Play ${track.title}`}
              >
                <Cover track={track} />
                <span className="cc-text">
                  <b>{track.title}</b>
                  <span>{track.uploader || "unknown artist"}</span>
                </span>
                <span className="cc-go">
                  {audio.isCurrent(track) && audio.playing ? <Equalizer playing bars={3} /> : <Play size={13} fill="currentColor" />}
                </span>
              </button>
            ))}
            <button type="button" className="continue-card ghost" onClick={() => setView("library")}>
              <span className="cc-text">
                <b>Open library</b>
                <span>liked · playlists · history</span>
              </span>
              <Headphones size={15} />
            </button>
          </div>
        </>
      )}

      <SectionHead right={<button type="button" className="link-btn" onClick={() => setView("search")}>See all</button>}>
        <span className="flame">
          <Sparkles size={15} /> Trending now
        </span>
      </SectionHead>
      <div className="shelf">
        {trending.length === 0
          ? Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="skeleton-card" aria-hidden="true" />
            ))
          : trending.map((track, index) => (
              <TrackCard key={`${track.id ?? track.title}-${index}`} track={track} rank={index + 1} delay={index * 40} />
            ))}
      </div>

      <SectionHead right={<span className="muted small">refreshed every 30 min</span>}>Made for you</SectionHead>
      <div className="shelf shelf-mixes">
        {shelves.length === 0
          ? Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="skeleton-card" aria-hidden="true" />
            ))
          : shelves.map((shelf, index) => {
              const lead = shelf.tracks?.[0];
              if (!lead) return null;
              return (
                <TrackCard
                  key={shelf.key}
                  track={lead}
                  mix
                  badge={shelf.title}
                  delay={index * 50}
                  onMixClick={() => void loadMix(shelf.key)}
                />
              );
            })}
      </div>

      <SectionHead>Moods</SectionHead>
      <div className="chips-row">
        {moods.map((mood) => (
          <button key={mood.key} type="button" className="chip" onClick={() => void loadMix(mood.key)}>
            {mood.title}
          </button>
        ))}
      </div>

      <div className="cards-grid">
        <Panel title="Quick search" icon={<Search size={14} />}>
          <form
            className="inline-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const query = miniQuery.trim();
              if (!query) return;
              try {
                const payload = await api.search(query, 5);
                setMiniResults(payload.results ?? []);
              } catch {
                setMiniResults([]);
              }
            }}
          >
            <input
              value={miniQuery}
              onChange={(event) => setMiniQuery(event.target.value)}
              placeholder="What do you want to hear?"
              type="search"
            />
            <button type="submit" className="pill-btn accent">
              Go
            </button>
          </form>
          <ul className="rows">
            {miniResults.length === 0 && <li className="empty-row">Results appear here.</li>}
            {miniResults.map((track, index) => (
              <li key={`${track.title}-${index}`} onClick={() => void play(track.query ?? track.title, "play_now")}>
                <Cover track={track} />
                <span className="tx">
                  <b>{track.title}</b>
                  <span>{fmtDuration(track.duration)}</span>
                </span>
                <Play size={13} className="chev" />
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Download" icon={<Download size={14} />}>
          <p className="muted small">Paste a link or type a name — the bot sends the file to your chat.</p>
          <form
            className="inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              openModal({ type: "download", query: downloadQuery, kind: quality });
            }}
          >
            <input
              value={downloadQuery}
              onChange={(event) => setDownloadQuery(event.target.value)}
              placeholder="Paste link or search…"
            />
            <button type="submit" className="pill-btn accent">
              <Download size={14} /> Get
            </button>
          </form>
          <div className="quality-row">
            <label>
              <input
                type="radio"
                name="quality"
                checked={quality === "audio"}
                onChange={() => setQuality("audio")}
              />
              <span>MP3 · 320 kbps</span>
            </label>
            <label>
              <input
                type="radio"
                name="quality"
                checked={quality === "video"}
                onChange={() => setQuality("video")}
              />
              <span>MP4 · 720p</span>
            </label>
          </div>
          <div className="source-row">
            <span className="source yt">YouTube</span>
            <span className="source">SoundCloud</span>
            <span className="source">Links</span>
            <span className="source">Replies</span>
          </div>
        </Panel>

        <Panel
          title="Listen together"
          icon={<Users size={14} />}
          tag={<span className="tag">live</span>}
          action={
            <button type="button" className="icon-btn sm" aria-label="Refresh rooms" onClick={() => void refreshRooms()}>
              <RefreshCw size={13} />
            </button>
          }
        >
          <ul className="rows">
            {rooms.length === 0 && <li className="empty-row">No active rooms yet.</li>}
            {rooms.slice(0, 3).map((room) => (
              <li key={room.chat_id} onClick={() => setView("rooms")}>
                <span className="rk">{room.playing && !room.paused ? "🔊" : "⏸"}</span>
                <span className="tx">
                  <b>{room.title}</b>
                  <span>{room.listeners} listening</span>
                </span>
                {room.track?.title && <span className="dur">{room.track.title.slice(0, 16)}</span>}
              </li>
            ))}
          </ul>
          <button type="button" className="pill-btn ghost wide" onClick={() => setView("rooms")}>
            Browse rooms
          </button>
        </Panel>

        <Panel
          title="Your library"
          icon={<Plus size={14} />}
          action={<button type="button" className="link-btn" onClick={() => setView("library")}>Open</button>}
        >
          <div className="lib-stats">
            <div>
              <b>{state?.favorites?.length ?? 0}</b>
              <span>liked</span>
            </div>
            <div>
              <b>{playlists.length}</b>
              <span>playlists</span>
            </div>
            <div>
              <b>{state?.history?.length ?? 0}</b>
              <span>played</span>
            </div>
          </div>
          <ul className="rows">
            {history.length === 0 && <li className="empty-row">Nothing played yet — start with a mix above.</li>}
            {history.map((track, index) => (
              <li key={`${track.id ?? track.title}-${index}`} onClick={() => void play(track.query ?? track.title, "play_now")}>
                <Cover track={track} />
                <span className="tx">
                  <b>{track.title}</b>
                  <span>{track.uploader || "unknown"}</span>
                </span>
                <span className="dur">{fmtDuration(track.duration)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="cta-row">
        <button
          type="button"
          className="cta"
          onClick={async () => {
            const liked = state?.favorites ?? [];
            if (!liked.length) {
              toast("No liked songs yet");
              return;
            }
            toast(`Queuing ${Math.min(liked.length, 25)} liked songs…`);
            for (const track of liked.slice(0, 25)) {
              await act("play", track.query ?? `${track.title} ${track.uploader ?? ""}`);
            }
            toast("Liked songs queued", "success");
          }}
        >
          <span>
            <b>Play your liked songs</b>
            <small>{state?.favorites?.length ?? 0} tracks ready to go</small>
          </span>
          <Play size={16} fill="currentColor" />
        </button>
        <button type="button" className="cta" onClick={() => void runSearch("lofi mix")}>
          <span>
            <b>Late-night lo-fi</b>
            <small>Instant mix, no thinking required</small>
          </span>
          <Sparkles size={16} />
        </button>
      </div>
    </section>
  );
}
