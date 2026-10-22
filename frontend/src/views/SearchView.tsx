import { Play, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { ResultRow } from "../components/ResultRow";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "songs", label: "Songs" },
  { key: "playlists", label: "Playlists" },
  { key: "artists", label: "Artists" },
] as const;

export function SearchView() {
  const {
    results,
    query,
    runSearch,
    searchFilter,
    setSearchFilter,
    recent,
    playlists,
    openPlaylist,
    play,
  } = useApp();
  const [value, setValue] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setValue(query);
  }, [query]);

  useEffect(() => {
    const focus = () => inputRef.current?.focus();
    window.addEventListener("vyron:focus-search", focus);
    return () => window.removeEventListener("vyron:focus-search", focus);
  }, []);

  const artistGroups = (() => {
    const groups = new Map<string, { name: string; tracks: number; cover?: string | null; query: string }>();
    for (const track of results) {
      const key = track.uploader || "unknown artist";
      const entry = groups.get(key);
      if (entry) entry.tracks += 1;
      else groups.set(key, { name: key, tracks: 1, cover: track.thumbnail, query: key });
    }
    return [...groups.values()];
  })();

  const playlistMatches = playlists.filter((playlist) =>
    playlist.name.toLowerCase().includes(query.toLowerCase())
  );

  const showSongs = searchFilter === "all" || searchFilter === "songs";
  const empty =
    (showSongs && results.length === 0) ||
    (searchFilter === "artists" && artistGroups.length === 0) ||
    (searchFilter === "playlists" && playlistMatches.length === 0);

  return (
    <section className="view active">
      <div className="view-head">
        <h1>Search</h1>
        <p className="muted">Songs, artists or links</p>
      </div>

      <form
        className="searchbar"
        onSubmit={(event) => {
          event.preventDefault();
          void runSearch(value);
        }}
      >
        <Search size={17} />
        <input
          ref={inputRef}
          id="vyron-search"
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Search or paste a YouTube link…"
          autoComplete="off"
        />
        {value && (
          <button
            type="button"
            className="clear-btn"
            aria-label="Clear"
            onClick={() => {
              setValue("");
              inputRef.current?.focus();
            }}
          >
            <X size={14} />
          </button>
        )}
        <button type="submit" className="search-go" aria-label="Search">
          <Search size={15} />
        </button>
      </form>

      <div className="tabs">
        {FILTERS.map((filter) => (
          <button
            key={filter.key}
            type="button"
            className={`tab ${searchFilter === filter.key ? "active" : ""}`}
            onClick={() => setSearchFilter(filter.key)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {showSongs && (
        <ul className="result-list">
          {results.map((track, index) => (
            <ResultRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
          ))}
        </ul>
      )}

      {searchFilter === "artists" && (
        <div className="artist-grid">
          {artistGroups.map((artist) => (
            <button
              key={artist.name}
              type="button"
              className="artist-card"
              onClick={() => void runSearch(artist.name, false)}
            >
              <Cover track={{ title: artist.name, thumbnail: artist.cover }} className="artist-cover" />
              <b>{artist.name}</b>
              <span>{artist.tracks} tracks</span>
            </button>
          ))}
        </div>
      )}

      {searchFilter === "playlists" && (
        <ul className="result-list">
          {playlistMatches.map((playlist) => (
            <li key={playlist.id} className="result" onClick={() => openPlaylist(playlist)}>
              <Cover track={{ title: playlist.name, thumbnail: playlist.covers?.[0] }} />
              <div className="info">
                <b>{playlist.name}</b>
                <span>
                  {playlist.count} tracks · {fmtDuration(playlist.duration)}
                </span>
              </div>
              <div className="acts">
                <button
                  type="button"
                  className="mini-action play"
                  aria-label="Play playlist"
                  onClick={(event) => {
                    event.stopPropagation();
                    void play(playlist.name, "play_now");
                  }}
                >
                  <Play size={14} fill="currentColor" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {empty && (
        <p className="empty-state">
          {query ? `No results for “${query}” — try another spelling or a link.` : "Type something above — results appear instantly."}
        </p>
      )}

      {recent.length > 0 && (
        <>
          <div className="section-head">
            <h2>Recent searches</h2>
          </div>
          <div className="chips-row">
            {recent.map((term) => (
              <button
                key={term}
                type="button"
                className="chip"
                onClick={() => {
                  setValue(term);
                  void runSearch(term, false);
                }}
              >
                {term}
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
