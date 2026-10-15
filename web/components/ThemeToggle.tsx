"use client";

import { useSyncExternalStore } from "react";

type Mode = "system" | "light" | "dark";
const KEY = "iddaa-lab-theme";
const EVT = "iddaa-lab-theme-change";
const NEXT: Record<Mode, Mode> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<Mode, string> = { system: "Tema: sistem", light: "Tema: açık", dark: "Tema: koyu" };

// Kaynak gerçeklik: <html data-theme> (ilk boyamadan önce layout'taki betik ayarlar)
function getMode(): Mode {
  const t = document.documentElement.dataset.theme;
  return t === "light" || t === "dark" ? t : "system";
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVT, cb);
  return () => window.removeEventListener(EVT, cb);
}

export default function ThemeToggle() {
  const mode = useSyncExternalStore<Mode>(subscribe, getMode, () => "system");

  function cycle() {
    const next = NEXT[mode];
    const root = document.documentElement;
    if (next === "system") delete root.dataset.theme;
    else root.dataset.theme = next;
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // kalıcılık yoksa yalnızca bu sekmede geçerli
    }
    window.dispatchEvent(new Event(EVT));
  }

  return (
    <button
      type="button"
      onClick={cycle}
      title={LABEL[mode]}
      aria-label={LABEL[mode]}
      className="grid h-8 w-8 place-items-center rounded-md border border-line text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
    >
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
        {mode === "dark" ? (
          <path d="M11.5 10.5A5.5 5.5 0 0 1 5.5 4.5a5.5 5.5 0 1 0 6 6Z" fill="currentColor" />
        ) : mode === "light" ? (
          <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="8" cy="8" r="3" />
            <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" />
          </g>
        ) : (
          <g fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 2.5v11A5.5 5.5 0 0 0 8 2.5Z" fill="currentColor" />
          </g>
        )}
      </svg>
    </button>
  );
}
