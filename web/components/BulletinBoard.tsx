"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { dayKey, kickoff, marketLine, odd, pct } from "@/lib/format";
import type { MarketOnlyRow, MatchRow, MatchesResponse } from "@/lib/types";
import { ConfidenceBadge, Crest, EmptyState, ProbBar } from "./ui";

type Sort = "time" | "value" | "certainty";

const dayFmt = new Intl.DateTimeFormat("tr-TR", { timeZone: "Europe/Istanbul", weekday: "short", day: "numeric", month: "short" });

function dayName(key: string, todayKey: string, tomorrowKey: string): string {
  if (key === todayKey) return "Bugün";
  if (key === tomorrowKey) return "Yarın";
  return dayFmt.format(new Date(`${key}T12:00:00Z`));
}

export default function BulletinBoard({ data, nowIso }: { data: MatchesResponse; nowIso: string }) {
  const todayKey = dayKey(nowIso);
  const tomorrowKey = dayKey(new Date(new Date(nowIso).getTime() + 86_400_000).toISOString());
  const days = useMemo(() => {
    const s = new Set<string>();
    data.items.forEach((m) => s.add(dayKey(m.match.date_utc)));
    data.market_only.forEach((m) => s.add(dayKey(m.kickoff_utc)));
    return [...s].sort();
  }, [data]);

  // Varsayılan gün: bültende model maçı olan ilk gün (yoksa ilk gün)
  const firstModelDay = useMemo(() => {
    const ds = data.items.filter((m) => m.covered && m.iddaa).map((m) => dayKey(m.match.date_utc)).sort();
    return ds[0] ?? days[0] ?? "all";
  }, [data.items, days]);
  const [day, setDay] = useState<string>(firstModelDay);
  const [league, setLeague] = useState<string>("all");
  const [onlyIddaa, setOnlyIddaa] = useState(true);
  const [onlyValue, setOnlyValue] = useState(false);
  const [sort, setSort] = useState<Sort>("time");
  const [query, setQuery] = useState("");

  const items = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr");
    let xs = data.items.filter((m) => day === "all" || dayKey(m.match.date_utc) === day);
    if (league !== "all") xs = xs.filter((m) => m.match.league === league);
    if (onlyIddaa) xs = xs.filter((m) => m.iddaa);
    if (onlyValue) xs = xs.filter((m) => m.iddaa?.best_value != null);
    if (q) xs = xs.filter((m) => `${m.match.home.name} ${m.match.away.name}`.toLocaleLowerCase("tr").includes(q));
    const certainty = (m: MatchRow) => Math.max(...Object.values(m.ms ?? { x: 0 }));
    if (sort === "value") xs = [...xs].sort((a, b) => (b.iddaa?.best_value?.p_blend ?? -9) - (a.iddaa?.best_value?.p_blend ?? -9));
    if (sort === "certainty") xs = [...xs].sort((a, b) => certainty(b) - certainty(a));
    return xs;
  }, [data.items, day, league, onlyIddaa, onlyValue, sort, query]);

  const marketOnly = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr");
    return data.market_only.filter(
      (m) => (day === "all" || dayKey(m.kickoff_utc) === day) && (!q || `${m.home} ${m.away}`.toLocaleLowerCase("tr").includes(q)),
    );
  }, [data.market_only, day, query]);

  const groups = useMemo(() => {
    if (sort !== "time") return [{ key: "all", label: "", rows: items }];
    const g = new Map<string, MatchRow[]>();
    for (const m of items) {
      const k = `${m.match.country} · ${m.match.league_name}`;
      g.set(k, [...(g.get(k) ?? []), m]);
    }
    return [...g.entries()].map(([k, rows]) => ({ key: k, label: k, rows }));
  }, [items, sort]);

  return (
    <div className="flex flex-col gap-5">
      {/* Filtreler: tek satır, grafiklerin üstünde */}
      <div className="panel rise flex flex-col gap-3 p-3">
        <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Gün">
          {["all", ...days].map((d) => (
            <button
              key={d}
              role="tab"
              aria-selected={day === d}
              onClick={() => setDay(d)}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                day === d ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2"
              }`}
            >
              {d === "all" ? "Tümü" : dayName(d, todayKey, tomorrowKey)}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="sr-only" htmlFor="league">Lig</label>
          <select
            id="league"
            value={league}
            onChange={(e) => setLeague(e.target.value)}
            className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-ink"
          >
            <option value="all">Tüm ligler ({data.leagues.length})</option>
            {data.leagues.map((l) => (
              <option key={l.slug} value={l.slug}>
                {l.country} · {l.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Sıralama"
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-ink"
          >
            <option value="time">Saate göre (lig grupları)</option>
            <option value="value">En güçlü öneri</option>
            <option value="certainty">En net favori</option>
          </select>
          <Toggle checked={onlyIddaa} onChange={setOnlyIddaa} label="Bültende olanlar" />
          <Toggle checked={onlyValue} onChange={setOnlyValue} label="Önerisi olanlar" />
          <input
            type="search"
            placeholder="Takım ara…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="ml-auto min-w-40 flex-1 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-ink placeholder:text-muted sm:max-w-60 sm:flex-none"
          />
        </div>
      </div>

      <p className="text-xs text-muted">
        {items.length} maç modelde · {marketOnly.length} maç yalnızca piyasa verisiyle · Olasılık çubuğu:{" "}
        <Key color="var(--home)" label="ev" /> <Key color="var(--draw)" label="beraberlik" /> <Key color="var(--away)" label="deplasman" />
      </p>

      {items.length === 0 ? (
        <EmptyState title="Bu filtrede maç yok">Filtreleri gevşetmeyi ya da başka bir gün seçmeyi dene.</EmptyState>
      ) : (
        groups.map((g, gi) => (
          <section key={g.key} className="rise" style={{ animationDelay: `${Math.min(gi, 8) * 40}ms` }}>
            {g.label && <h2 className="kicker mb-2 px-1">{g.label}</h2>}
            <div className="panel divide-y divide-line overflow-hidden">
              {g.rows.map((m) => (
                <Row key={m.match.id} m={m} />
              ))}
            </div>
          </section>
        ))
      )}

      {marketOnly.length > 0 && <MarketOnly rows={marketOnly} />}
    </div>
  );
}

function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2 w-2 rounded-[2px]" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 ${checked ? "border-accent/60 text-ink" : "border-line text-ink-2"}`}
    >
      <span className={`relative h-3.5 w-6 rounded-full transition-colors ${checked ? "bg-accent" : "bg-surface-3"}`} aria-hidden>
        <span className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-surface transition-all ${checked ? "left-3" : "left-0.5"}`} />
      </span>
      {label}
    </button>
  );
}

function OddCell({ label, o, p }: { label: string; o: number | undefined; p: number | undefined }) {
  return (
    <div className="flex flex-col items-center rounded-md bg-surface-2 px-2 py-1">
      <span className="text-[0.62rem] text-muted">{label}</span>
      <span className="num text-sm font-semibold">{odd(o)}</span>
      <span className="num text-[0.62rem] text-muted" title="Model olasılığı">{pct(p)}</span>
    </div>
  );
}

function Row({ m }: { m: MatchRow }) {
  const { match } = m;
  if (!m.covered) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 text-sm text-muted">
        <span className="num w-12">{kickoff(match.date_utc)}</span>
        <span className="truncate">
          {match.home.name} – {match.away.name}
        </span>
        <span className="ml-auto text-xs">{m.coverage_note}</span>
      </div>
    );
  }
  const ms = m.ms ?? {};
  const best = m.iddaa?.best_value;
  return (
    <Link
      href={`/mac/${match.id}`}
      className="group grid grid-cols-1 gap-3 px-4 py-3 transition-colors hover:bg-surface-2 lg:grid-cols-[64px_minmax(0,1.25fr)_minmax(0,1fr)_auto_minmax(0,0.9fr)] lg:items-center"
    >
      <div className="flex items-center gap-2 lg:flex-col lg:items-start lg:gap-0.5">
        <span className="num text-base font-semibold">{kickoff(match.date_utc)}</span>
        {m.confidence && m.confidence !== "yüksek" && <ConfidenceBadge level={m.confidence} />}
        {match.lineup_confirmed && <span className="text-[0.65rem] text-good-ink">✓ kadro</span>}
      </div>

      <div className="flex min-w-0 flex-col gap-1.5">
        <TeamLine name={match.home.name} logo={match.home.logo} xg={m.lambda_home} />
        <TeamLine name={match.away.name} logo={match.away.logo} xg={m.lambda_away} />
      </div>

      <div className="min-w-0">
        <ProbBar ms={ms} />
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[0.72rem] text-ink-2">
          <span>
            2.5 Üst <b className="num font-semibold text-ink">{pct(m.au25?.["Üst"])}</b>
          </span>
          <span>
            KG Var <b className="num font-semibold text-ink">{pct(m.kg?.["Var"])}</b>
          </span>
          {m.top_score && (
            <span>
              En olası <b className="num font-semibold text-ink">{m.top_score.home}-{m.top_score.away}</b>
            </span>
          )}
        </div>
      </div>

      <div className="flex gap-1">
        {m.iddaa?.ms_odds ? (
          <>
            <OddCell label="1" o={m.iddaa.ms_odds["1"]} p={ms["1"]} />
            <OddCell label="X" o={m.iddaa.ms_odds["0"]} p={ms["0"]} />
            <OddCell label="2" o={m.iddaa.ms_odds["2"]} p={ms["2"]} />
          </>
        ) : (
          <span className="text-xs text-muted">Bültende yok</span>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-1 text-xs">
        {best ? (
          <div className="flex flex-wrap items-center gap-1.5" title={`Model önerisi · EV ${(best.ev * 100).toFixed(1)}%${best.validated ? "" : " · doğrulanmamış pazar"}`}>
            <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wider text-accent">Öneri</span>
            <span className="truncate text-ink-2">
              {marketLine(best.label, best.line)}: <b className="text-ink">{outcomeText(best.name)}</b>{" "}
              <span className="num">@{odd(best.odd)} · {pct(best.p_blend)}</span>
            </span>
          </div>
        ) : m.iddaa ? (
          <span className="text-muted">Model piyasadan farklı düşünmüyor: öneri yok</span>
        ) : null}
        {m.top_players && m.top_players.length > 0 && (
          <span className="truncate text-ink-2" title="Simülasyonda en az 1 isabetli şut olasılığı">
            ◎ {m.top_players[0].name} <span className="num">{pct(m.top_players[0].p_sot_1)}</span> isabetli şut
          </span>
        )}
      </div>
    </Link>
  );
}

function outcomeText(name: string): string {
  if (name === "0") return "X";
  return name.replace(/\b0\b/g, "X").replace(/ ve /g, "-");
}

function TeamLine({ name, logo, xg }: { name: string; logo?: string | null; xg?: number }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Crest team={{ name, logo: logo ?? null }} size={22} />
      <span className="truncate font-medium">{name}</span>
      {xg != null && (
        <span className="num ml-auto shrink-0 text-xs text-muted" title="Beklenen gol (model λ)">
          {xg.toFixed(2)}
        </span>
      )}
    </div>
  );
}

function MarketOnly({ rows }: { rows: MarketOnlyRow[] }) {
  const [open, setOpen] = useState(false);
  const shown = open ? rows : rows.slice(0, 12);
  return (
    <section className="mt-4">
      <div className="mb-2 flex items-baseline justify-between px-1">
        <h2 className="font-display text-xl font-extrabold uppercase">Model kapsamı dışındaki maçlar</h2>
        <span className="text-xs text-muted">Yalnızca iddaa oranından (marjı arındırılmış) piyasa olasılığı · kupona alınmaz</span>
      </div>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Saat</th>
              <th className="px-3 py-2 font-medium">Lig</th>
              <th className="px-3 py-2 font-medium">Maç</th>
              <th className="px-3 py-2 text-right font-medium">1 / X / 2</th>
              <th className="px-3 py-2 font-medium">Piyasa olasılığı</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {shown.map((r) => (
              <tr key={r.event_id}>
                <td className="num px-3 py-2">{kickoff(r.kickoff_utc)}</td>
                <td className="max-w-48 truncate px-3 py-2 text-ink-2">{r.competition ?? "–"}</td>
                <td className="px-3 py-2">
                  {r.home} – {r.away}
                </td>
                <td className="num px-3 py-2 text-right">
                  {r.ms_odds ? `${odd(r.ms_odds["1"])} / ${odd(r.ms_odds["0"])} / ${odd(r.ms_odds["2"])}` : "–"}
                </td>
                <td className="w-56 px-3 py-2">{r.ms_market_prob ? <ProbBar ms={r.ms_market_prob} height={6} showLabels={false} /> : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 12 && (
        <button type="button" onClick={() => setOpen(!open)} className="mt-2 text-sm text-ink-2 underline-offset-4 hover:underline">
          {open ? "Daha az göster" : `Tümünü göster (${rows.length})`}
        </button>
      )}
    </section>
  );
}
