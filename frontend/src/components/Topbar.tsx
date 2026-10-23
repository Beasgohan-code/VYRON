import { Bell, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { initials } from "../lib/format";
import { useApp } from "../lib/store";

export function Topbar() {
  const { runSearch, setView, state, toast, view } = useApp();
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focus = () => inputRef.current?.focus();
    window.addEventListener("vyron:focus-search", focus);
    return () => window.removeEventListener("vyron:focus-search", focus);
  }, []);
  const user = state?.user ?? {};

  return (
    <header className="topbar">
      <form
        className="search-pill"
        onSubmit={(event) => {
          event.preventDefault();
          const query = value.trim();
          if (!query) return;
          setView("search");
          void runSearch(query);
        }}
        role="search"
      >
        <Search size={16} />
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Search songs, artists or paste a link…"
          aria-label="Search"
          autoComplete="off"
        />
        <kbd>/</kbd>
      </form>

      <div className="topbar-actions">
        <button
          type="button"
          className="icon-btn"
          aria-label="Notifications"
          onClick={() => toast("No new notifications")}
        >
          <Bell size={17} />
        </button>
        <button
          type="button"
          className="avatar"
          aria-label="Profile"
          onClick={() => setView(view === "profile" ? "home" : "profile")}
        >
          {initials(user.name)}
        </button>
      </div>
    </header>
  );
}
