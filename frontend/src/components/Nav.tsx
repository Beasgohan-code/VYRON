import { Compass, Home, Library, Radio, ShieldCheck, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useApp } from "../lib/store";
import type { View } from "../lib/types";

interface Item {
  view: View;
  label: string;
  icon: LucideIcon;
  owner?: boolean;
}

const ITEMS: Item[] = [
  { view: "home", label: "Home", icon: Home },
  { view: "search", label: "Search", icon: Compass },
  { view: "library", label: "Library", icon: Library },
  { view: "rooms", label: "Rooms", icon: Radio },
  { view: "profile", label: "You", icon: User },
  { view: "api", label: "Owner", icon: ShieldCheck, owner: true },
];

function useItems(): Item[] {
  const { state } = useApp();
  const isOwner = Boolean(state?.owner);
  return ITEMS.filter((item) => !item.owner || isOwner);
}

/** Desktop rail. */
export function Rail() {
  const { view, setView } = useApp();
  const items = useItems();

  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail-brand">
        <span className="rail-mark">
          <img src={`${import.meta.env.BASE_URL}brand/avatar.jpg`} alt="" />
        </span>
        <span className="rail-word">
          VYRON
          <i>music app</i>
        </span>
      </div>

      <div className="rail-links">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.view}
              type="button"
              className={`rail-link ${view === item.view ? "active" : ""}`}
              onClick={() => setView(item.view)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      <div className="rail-foot">
        <span className="live-dot" />
        <span>voice + web</span>
      </div>
    </nav>
  );
}

/** Mobile tab bar. */
export function Tabs() {
  const { view, setView } = useApp();
  const items = useItems();

  return (
    <nav className="tabs" aria-label="Sections">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.view}
            type="button"
            className={`tab-item ${view === item.view ? "active" : ""}`}
            onClick={() => setView(item.view)}
            aria-current={view === item.view ? "page" : undefined}
          >
            <Icon size={20} />
            <span className="tab-label">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
