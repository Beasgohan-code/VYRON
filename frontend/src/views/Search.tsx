import { Search as SearchIcon, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { TrackRow } from "../components/TrackRow";
import { useViewReveal } from "../lib/anim";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "songs", label: "Songs" },
  { key: "artists", label: "Artists" },
  { key: "playlists", label: "Playlists" },
] as const;

export function Search() {
  const {
    results,
    query,
    runSearch,
    searchFilter,
    setSearchFilter,
    recent,
    playlists,
    openPlaylist,
    searching,
  } = useApp();
  const [value, setValue] = useState(query);
  const input = useRef<HTMLInputElement>(null);
  const stage = useViewReveal<HTMLDivElement>("search", ".track-row, .result-block");

  useEffect(() => setValue(query), [query]);

  useEffect(() => {
    const focus = () => input.current?.focus();
    window.addEventListener("vyron:focus-search", focus);
    return () => window.removeEventListener("vyron:focus-search", focus);
  }, []);

  const artists = (() => {
    const groups = new Map<string, { name: string; count: number; cover?: string | null }>();
    for (const track of results) {
      const name = track.uploader || "unknown artist";
      const entry = groups.get(name);
      if (entry) entry.count += 1;
      else groups.set(name, { name, count: 1, cover: track.thumbnail });
    }
    return [...groups.values()];
  })();

  const playlistMatches = query
    ? playlists.filter((playlist) => playlist.name.toLowerCase().includes(query.toLowerCase()))
    : [];

  const showSongs = searchFilter === "all" || searchFilter === "songs";
  const idle = !query && results.length === 0 && !searching;

  return (
    <div className="stage" ref={stage}>
      <header className="screen-head">
        <h1>Search</h1>
        <p>Songs, artists or a link — start typing.</p>
      </header>

      <form
        className="field"
        onSubmit={(event) => {
          event.preventDefault();
          void runSearch(value);
        }}
      >
        <SearchIcon size={18} className="field-icon" />
        <input
          ref={input}
          id="vyron-search"
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Search songs, artists or paste a link"
          autoComplete="off"
          spellCheck={false}
        />
        {value && (
          <button
            type="button"
            className="field-clear"
            aria-label="Clear"
            onClick={() => {
              setValue("");
              input.current?.focus();
            }}
          >
            <X size={15} />
          </button>
        )}
        <button type="submit" className="field-go" aria-label="Search">
          <SearchIcon size={16} />
        </button>
      </form>

      <div className="chips">
        {FILTERS.map((filter) => (
          <button
            key={filter.key}
            type="button"
            className={`chip ${searchFilter === filter.key ? "active" : ""}`}
            onClick={() => setSearchFilter(filter.key)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {idle && (
        <section className="result-block">
          {recent.length > 0 ? (
            <>
              <header className="section-head">
                <h2>Recent</h2>
                <button type="button" className="section-link" onClick={() => void runSearch(recent[0])}>
                  Search “{recent[0]}” again
                </button>
              </header>
              <div className="chips">
                {recent.map((term) => (
                  <button key={term} type="button" className="chip ghost" onClick={() => void runSearch(term)}>
                    {term}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="empty">
              <span className="empty-icon">
                <Sparkles size={20} />
              </span>
              <b>Find your next favourite</b>
              <p>Type a name, paste a YouTube link, or reply to a file in the bot — it all lands here.</p>
            </div>
          )}
        </section>
      )}

      {searching && (
        <ul className="rows" aria-hidden="true">
          {Array.from({ length: 6 }, (_, index) => (
            <li key={index} className="skeleton-row">
              <span className="skeleton skeleton-art" />
              <span className="skeleton-line" style={{ width: `${70 - index * 6}%` }} />
            </li>
          ))}
        </ul>
      )}

      {!searching && showSongs && results.length > 0 && (
        <section className="result-block">
          <header className="section-head">
            <h2>Results</h2>
            <span className="fine">
              {results.length} track{results.length === 1 ? "" : "s"} for “{query}”
            </span>
          </header>
          <ul className="rows">
            {results.map((track, index) => (
              <TrackRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
            ))}
          </ul>
        </section>
      )}

      {!searching && searchFilter === "artists" && (
        <section className="result-block">
          {artists.length === 0 ? (
            <div className="empty">
              <b>No artists found</b>
              <p>Search returned no channels for “{query}”.</p>
            </div>
          ) : (
            <div className="card-grid">
              {artists.map((artist) => (
                <button
                  key={artist.name}
                  type="button"
                  className="artist-card"
                  onClick={() => void runSearch(artist.name)}
                >
                  <Cover track={{ title: artist.name, thumbnail: artist.cover }} monogram />
                  <b>{artist.name}</b>
                  <span>{artist.count} tracks</span>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {searchFilter === "playlists" && (
        <section className="result-block">
          {playlistMatches.length === 0 ? (
            <div className="empty">
              <b>No playlists match</b>
              <p>Your saved playlists show up here as you name them.</p>
            </div>
          ) : (
            <ul className="rows">
              {playlistMatches.map((playlist) => (
                <li key={playlist.id} className="track-row" onClick={() => openPlaylist(playlist)}>
                  <span className="tr-art">
                    <Cover track={{ title: playlist.name, thumbnail: playlist.covers?.[0] }} />
                  </span>
                  <span className="tr-main">
                    <b className="tr-title">{playlist.name}</b>
                    <span className="tr-sub">
                      {playlist.count} tracks · {fmtDuration(playlist.duration)}
                    </span>
                  </span>
                  <span className="tr-dur">▸</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {!searching && showSongs && results.length === 0 && !idle && (
        <div className="empty">
          <b>Nothing for “{query}”</b>
          <p>Try a different spelling, the artist name, or paste a direct link.</p>
        </div>
      )}
    </div>
  );
}
