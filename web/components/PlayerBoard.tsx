"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { kickoff, pct } from "@/lib/format";
import type { TopPlayer, TopPlayersResponse } from "@/lib/types";
import { Crest, EmptyState } from "./ui";

type SortKey = "p_sot_1" | "p_sot_2" | "p_shots_2" | "p_shots_3" | "p_goal" | "exp_shots";
const COLS: { key: SortKey; label: string; title: string }[] = [
  { key: "exp_shots", label: "Şut ort.", title: "Beklenen şut" },
  { key: "p_shots_2", label: "2+ şut", title: "En az 2 şut" },
  { key: "p_shots_3", label: "3+ şut", title: "En az 3 şut" },
  { key: "p_sot_1", label: "1+ isabet", title: "En az 1 isabetli şut" },
  { key: "p_sot_2", label: "2+ isabet", title: "En az 2 isabetli şut" },
  { key: "p_goal", label: "Gol", title: "Gol atma olasılığı" },
];
const POS: Record<string, string> = { all: "Tüm mevkiler", F: "Forvet", M: "Orta saha", D: "Defans" };

export default function PlayerBoard({ data }: { data: TopPlayersResponse }) {
  const [sort, setSort] = useState<SortKey>("p_sot_1");
  const [pos, setPos] = useState("all");
  const [league, setLeague] = useState("all");
  const [onlyConfirmed, setOnlyConfirmed] = useState(false);
  const [q, setQ] = useState("");
  const leagues = useMemo(() => [...new Set(data.items.map((p) => p.league_name))].sort(), [data.items]);

  const rows = useMemo(() => {
    const qq = q.trim().toLocaleLowerCase("tr");
    return data.items
      .filter((p) => (pos === "all" || p.pos_group === pos) && (league === "all" || p.league_name === league))
      .filter((p) => !onlyConfirmed || p.lineup_source === "resmi")
      .filter((p) => !qq || `${p.name} ${p.team}`.toLocaleLowerCase("tr").includes(qq))
      .sort((a, b) => b[sort] - a[sort])
      .slice(0, 150);
  }, [data.items, pos, league, onlyConfirmed, q, sort]);

  return (
    <div className="flex flex-col gap-4">
      <div className="panel flex flex-wrap items-center gap-2 p-3 text-sm">
        <select aria-label="Mevki" value={pos} onChange={(e) => setPos(e.target.value)} className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5">
          {Object.entries(POS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select aria-label="Lig" value={league} onChange={(e) => setLeague(e.target.value)} className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5">
          <option value="all">Tüm ligler</option>
          {leagues.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-ink-2">
          <input type="checkbox" checked={onlyConfirmed} onChange={(e) => setOnlyConfirmed(e.target.checked)} className="accent-[var(--accent)]" />
          Yalnızca resmi kadro
        </label>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Oyuncu / takım ara…"
          className="ml-auto min-w-44 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 placeholder:text-muted"
        />
      </div>
      <p className="text-xs text-muted">
        {data.total} oyuncu projeksiyonu (oynama olasılığı ≥ %50) · ilk 150 gösteriliyor. iddaa bülteni oyuncu pazarı
        yayınlamadığından bunlar oran karşılaştırması olmadan saf model olasılıklarıdır.
      </p>
      {rows.length === 0 ? (
        <EmptyState title="Filtreye uyan oyuncu yok" />
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Oyuncu</th>
                <th className="px-2 py-2 font-medium">Maç</th>
                <th className="px-2 py-2 font-medium" title="İlk 11 olasılığı / kadro kaynağı">İlk 11</th>
                {COLS.map((c) => (
                  <th key={c.key} className="px-2 py-2 text-right font-medium">
                    <button type="button" title={c.title} onClick={() => setSort(c.key)} className={`hover:text-ink ${sort === c.key ? "text-ink underline underline-offset-4" : ""}`}>
                      {c.label}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {rows.map((p) => (
                <Row key={`${p.match_id}-${p.player_id}`} p={p} sort={sort} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ p, sort }: { p: TopPlayer; sort: SortKey }) {
  const color = p.side === "home" ? "var(--home)" : "var(--away)";
  return (
    <tr className="hover:bg-surface-2">
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <Crest team={{ name: p.team, logo: p.team_logo }} size={20} />
          <div className="min-w-0">
            <p className="truncate font-medium">
              {p.name}
              {p.flags.length > 0 && (
                <span className="ml-1 cursor-help text-warn" title={p.flags.join(" · ")} aria-label={p.flags.join(" · ")}>
                  ⚠
                </span>
              )}
            </p>
            <p className="truncate text-xs text-muted">
              {p.team} · {p.position ?? p.pos_group}
            </p>
          </div>
        </div>
      </td>
      <td className="px-2 py-2 text-xs">
        <Link href={`/mac/${p.match_id}`} className="hover:underline">
          vs {p.opponent}
        </Link>
        <p className="text-muted">
          <span className="num">{kickoff(p.date_utc)}</span> · {p.league_name}
        </p>
      </td>
      <td className="num px-2 py-2 text-xs">
        {pct(p.p_start)} <span className={p.lineup_source === "resmi" ? "text-good-ink" : "text-muted"}>{p.lineup_source === "resmi" ? "✓ resmi" : "tahmini"}</span>
      </td>
      {COLS.map((c) => {
        const v = p[c.key];
        const isPct = c.key !== "exp_shots";
        return (
          <td key={c.key} className="px-2 py-2 text-right">
            <div className="flex items-center justify-end gap-2">
              {c.key === sort && isPct && (
                <span className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-surface-3 md:block" aria-hidden>
                  <span className="block h-full rounded-full" style={{ width: `${v * 100}%`, background: color }} />
                </span>
              )}
              <span className={`num ${c.key === sort ? "font-semibold text-ink" : "text-ink-2"}`}>{isPct ? pct(v) : v.toFixed(2)}</span>
            </div>
          </td>
        );
      })}
    </tr>
  );
}
