import { ArrowRight, Download, Headphones, Play, Radio, Search, Sparkles, Users } from "lucide-react";
import { useApp } from "../lib/store";
import { greeting } from "../lib/format";
import { Cover } from "../components/Cover";
import { Tile } from "../components/Tile";
import { Aurora } from "../components/Aurora";
import { Count } from "../components/Count";
import { Equalizer } from "../components/Equalizer";
import { useViewReveal } from "../lib/anim";

export function Home() {
  const {
    home,
    state,
    audio,
    play,
    loadMix,
    setView,
    openModal,
    rooms,
    playlists,
    act,
    toast,
    runSearch,
  } = useApp();
  const stage = useViewReveal<HTMLDivElement>("home", ".stage-block");

  const loading = home === null;
  const trending = home?.trending ?? [];
  const shelves = home?.shelves ?? [];
  const moods = home?.moods ?? [];
  const history = (state?.history ?? []).slice(0, 8);
  const stack = trending.slice(0, 3);

  return (
    <div className="stage" ref={stage}>
      <section className="hero stage-block">
        <div className="hero-art" aria-hidden="true" />
        <div className="hero-scrim" aria-hidden="true" />
        <Aurora className="hero-aurora" tone="violet" />
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="eyebrow-pulse" />
            <Sparkles size={13} />
            {state?.chat?.title ? `in ${state.chat.title}` : "your listening room"}
          </span>
          <h1 className="hero-title">
            {greeting()}
            <em>{home?.hero.headline ?? "Music hits different here."}</em>
          </h1>
          <p className="hero-sub">
            {home?.hero.subline ?? "Search for a song, or start playback from the bot's voice chat."}
          </p>

          <div className="hero-cta">
            {audio.track ? (
              <button type="button" className="btn btn-primary" onClick={() => audio.setExpanded(true)}>
                <Equalizer playing={audio.playing} bars={4} />
                Resume
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                disabled={!trending.length}
                onClick={() => {
                  const pick = trending[Math.floor(Math.random() * trending.length)];
                  if (pick) void play(pick, "play_now");
                  else setView("search");
                }}
              >
                <Play size={16} fill="currentColor" /> Surprise me
              </button>
            )}
            <button type="button" className="btn btn-ghost" onClick={() => setView("search")}>
              <Search size={15} /> Search
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => openModal({ type: "download" })}>
              <Download size={15} /> Download
            </button>
          </div>

          <div className="hero-stats">
            <span className="hero-stat">
              <b>
                <Count value={state?.favorites?.length ?? 0} />
              </b>
              liked
            </span>
            <span className="hero-stat">
              <b>
                <Count value={playlists.length} />
              </b>
              playlists
            </span>
            <span className="hero-stat">
              <b>
                <Count value={rooms.length} />
              </b>
              live rooms
            </span>
          </div>
        </div>

        <div className="hero-stack" aria-hidden="true">
          {stack.length === 0 && <div className="hero-stack-fallback" />}
          {stack.map((track, index) => (
            <span key={track.id ?? index} className={`hero-card hero-card-${index}`}>
              <Cover track={track} />
            </span>
          ))}
          {stack.length > 0 && (
            <span className="hero-stack-note">
              <Radio size={13} /> {trending.length} tracks trending now
            </span>
          )}
          {stack.length === 0 && (
            <span className="hero-stack-note">
              <Radio size={13} /> {state?.streaming ? "voice chat ready" : "file mode"}
            </span>
          )}
        </div>
      </section>

      {history.length > 0 && (
        <section className="stage-block">
          <header className="section-head">
            <h2>Continue listening</h2>
            <button type="button" className="section-link" onClick={() => setView("library")}>
              Library <ArrowRight size={13} />
            </button>
          </header>
          <div className="row-scroll">
            {history.map((track, index) => (
              <Tile key={`${track.id ?? track.title}-${index}`} track={track} wide />
            ))}
          </div>
        </section>
      )}

      <section className="stage-block">
        <header className="section-head">
          <h2>Trending now</h2>
          <button type="button" className="section-link" onClick={() => setView("search")}>
            See all <ArrowRight size={13} />
          </button>
        </header>
        <div className="row-scroll">
          {loading &&
            Array.from({ length: 5 }, (_, index) => <div key={index} className="tile skeleton-tile" />)}
          {!loading &&
            trending.slice(0, 12).map((track, index) => (
              <Tile key={track.id ?? `${track.title}-${index}`} track={track} rank={index + 1} />
            ))}
          {!loading && trending.length === 0 && (
            <div className="empty">
              <span className="empty-icon">
                <Sparkles size={20} />
              </span>
              <b>Charts are still filling up</b>
              <p>They build from what people actually play. Search for something you already love.</p>
              <button type="button" className="btn btn-primary" onClick={() => setView("search")}>
                <Search size={15} /> Search music
              </button>
            </div>
          )}
        </div>
      </section>

      {(loading || shelves.length > 0) && (
        <section className="stage-block">
          <header className="section-head">
            <h2>Made for you</h2>
            <span className="fine">refreshed every 30 min</span>
          </header>
          <div className="row-scroll">
            {loading &&
              Array.from({ length: 4 }, (_, index) => <div key={index} className="tile skeleton-tile" />)}
            {!loading &&
              shelves.map((shelf) => {
                const lead = shelf.tracks?.[0];
                if (!lead) return null;
                return (
                  <Tile
                    key={shelf.key}
                    track={lead}
                    badge={shelf.title}
                    onPlay={() => void loadMix(shelf.key)}
                  />
                );
              })}
          </div>
        </section>
      )}

      {moods.length > 0 && (
        <section className="stage-block">
          <header className="section-head">
            <h2>Moods</h2>
          </header>
          <div className="chips">
            {moods.map((mood) => (
              <button key={mood.key} type="button" className="chip" onClick={() => void loadMix(mood.key)}>
                {mood.title}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="stage-block">
        <header className="section-head">
          <h2>Listen together</h2>
          <button type="button" className="section-link" onClick={() => setView("rooms")}>
            All rooms <ArrowRight size={13} />
          </button>
        </header>
        {rooms.length === 0 ? (
          <div className="empty inline">
            <span className="empty-icon">
              <Users size={18} />
            </span>
            <b>No room is playing right now</b>
            <p>Start one with /play in a group voice chat — it shows up here instantly.</p>
          </div>
        ) : (
          <div className="room-strip">
            {rooms.slice(0, 4).map((room) => (
              <button key={room.chat_id} type="button" className="room-chip" onClick={() => setView("rooms")}>
                <span className={`live-dot ${room.playing && !room.paused ? "" : "idle"}`} />
                <span className="room-chip-text">
                  <b>{room.title}</b>
                  <span>
                    {room.listeners} listening
                    {room.track?.title ? ` · ${room.track.title}` : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="stage-block">
        <div className="quick-grid">
          <button
            type="button"
            className="quick"
            onClick={async () => {
              const liked = state?.favorites ?? [];
              if (!liked.length) {
                toast("No liked songs yet");
                return;
              }
              toast(`Queueing ${Math.min(liked.length, 25)} liked songs…`);
              for (const track of liked.slice(0, 25)) {
                await act("play", track.query ?? `${track.title} ${track.uploader ?? ""}`);
              }
              toast("Liked songs queued", "success");
            }}
          >
            <Headphones size={18} />
            <b>Play liked songs</b>
            <span>{state?.favorites?.length ?? 0} ready to go</span>
          </button>

          <button type="button" className="quick" onClick={() => void runSearch("late night lofi")}>
            <Sparkles size={18} />
            <b>Late-night lo-fi</b>
            <span>instant mix, no thinking</span>
          </button>

          <button
            type="button"
            className="quick"
            onClick={() => audio.queue[0] && void play(audio.queue[0], "play_now")}
            disabled={!audio.queue.length}
          >
            <Play size={18} />
            <b>Back to the queue</b>
            <span>{audio.queue.length} tracks waiting</span>
          </button>
        </div>
      </section>

      {!loading && trending.length === 0 && shelves.length === 0 && (
        <p className="fine center">
          Discovery is quiet right now — search works even when charts do not.
        </p>
      )}
    </div>
  );
}
