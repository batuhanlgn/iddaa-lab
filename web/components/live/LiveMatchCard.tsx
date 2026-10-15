"use client";

import Link from "next/link";
import { kickoff, marketLine, odd, pct, signedPct } from "@/lib/format";
import type { EspnLive, IddaaLive, LiveBaseItem } from "@/lib/live-feed";
import { liveDist, nextGoalProbs, outcomeCond, pickStatus, restOfMatchProbs, type PreModel } from "@/lib/live-model";
import { Crest, ProbBar } from "../ui";
import StatusChip from "./StatusChip";

const VALUE_EV = 0.05;
const VALUE_MIN_P = 0.25;

function RedCards({ n }: { n: number }) {
  if (n <= 0) return null;
  return (
    <span className="inline-flex gap-0.5" title={`${n} kırmızı kart`} aria-label={`${n} kırmızı kart`}>
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className="inline-block h-3.5 w-2.5 rounded-[2px] bg-critical" />
      ))}
    </span>
  );
}

function statusBadge(e: EspnLive | undefined, item: LiveBaseItem) {
  if (!e || !e.state.started) return <span className="num text-xs text-muted">{kickoff(item.date_utc)}</span>;
  if (e.state.finished) return <span className="rounded bg-surface-3 px-1.5 py-0.5 text-xs font-semibold text-ink-2">MS</span>;
  if (e.state.halftime) return <span className="rounded bg-warn/20 px-1.5 py-0.5 text-xs font-semibold text-warn">İY</span>;
  return (
    <span className="flex items-center gap-1 rounded bg-critical/15 px-1.5 py-0.5 text-xs font-semibold text-critical-ink">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-critical" aria-hidden />
      <span className="num">{e.clock || `${e.state.minute}'`}</span>
    </span>
  );
}

interface Row {
  label: string;
  outcomes: { name: string; odd: number; p: number | null }[];
}

function marketRows(il: IddaaLive, pre: PreModel, e: EspnLive): Row[] {
  const dist = liveDist(pre, e.state);
  const rows: Row[] = [];
  for (const m of il.markets) {
    if (m.st === 4) {
      rows.push({ label: "Maç sonucu", outcomes: m.outcomes.map((o) => {
        const c = outcomeCond("ms", null, o.name);
        return { name: o.name, odd: o.odd, p: c ? dist.prob(c) : null };
      }) });
    } else if (m.st === 14 && m.sov) {
      rows.push({ label: `Alt/Üst ${m.sov}`, outcomes: m.outcomes.map((o) => {
        const c = outcomeCond("au", m.sov, o.name);
        return { name: o.name, odd: o.odd, p: c ? dist.prob(c) : null };
      }) });
    } else if (m.st === 34) {
      const ng = nextGoalProbs(pre, e.state);
      rows.push({ label: `${m.sov ?? "Sıradaki"}. golü kim atar`, outcomes: m.outcomes.map((o) => ({
        name: o.name, odd: o.odd, p: o.name === "1" ? ng.home : o.name === "2" ? ng.away : o.name === "Olmaz" ? ng.none : null,
      })) });
    } else if (m.st === 23) {
      const r = restOfMatchProbs(pre, e.state);
      rows.push({ label: "Kalan süre sonucu", outcomes: m.outcomes.map((o) => ({
        name: o.name, odd: o.odd, p: o.name in r ? r[o.name as "1" | "0" | "2"] : null,
      })) });
    }
  }
  return rows;
}

const OUT: Record<string, string> = { "0": "X", Olmaz: "Gol yok" };

export default function LiveMatchCard({ item, espn, il }: { item: LiveBaseItem; espn: EspnLive | undefined; il: IddaaLive | null }) {
  const pre: PreModel = item.model;
  const s = espn?.state;
  const live = s && s.started && !s.finished ? liveDist(pre, s) : null;
  const ms = live
    ? { "1": live.prob((X, Y) => X > Y), "0": live.prob((X, Y) => X === Y), "2": live.prob((X, Y) => X < Y) }
    : null;
  const kg = live ? live.prob((X, Y) => X > 0 && Y > 0) : null;
  const au25 = live ? live.prob((X, Y) => X + Y > 2.5) : null;
  const rows = il && espn && s && s.started && !s.finished ? marketRows(il, pre, espn) : [];
  const scoreMismatch = il?.score && s && s.started && (il.score[0] !== s.home || il.score[1] !== s.away);
  const lowConf = item.model.confidence === "düşük";

  return (
    <article className="panel flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2 text-xs text-muted">
        <span className="truncate">{item.country} · {item.league_name}</span>
        {statusBadge(espn, item)}
      </div>

      <Link href={`/mac/${item.id}`} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 hover:opacity-90">
        {(["home", "away"] as const).map((side) => (
          <div key={side} className="contents">
            <div className="flex min-w-0 items-center gap-2">
              <Crest team={{ name: item[side].name, logo: item[side].logo ?? null }} size={22} />
              <span className="truncate font-semibold">{item[side].name}</span>
              <RedCards n={side === "home" ? (s?.redHome ?? 0) : (s?.redAway ?? 0)} />
            </div>
            <span className="num text-2xl font-bold">{s?.started ? (side === "home" ? s.home : s.away) : "–"}</span>
          </div>
        ))}
      </Link>
      {s?.started && s.htHome != null && <p className="num -mt-1 text-xs text-muted">İY {s.htHome}-{s.htAway}</p>}

      {espn && espn.events.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 text-[0.7rem]">
          {espn.events.filter((x) => x.type !== "yellow").slice(-6).map((x, i) => (
            <li key={i} className="flex items-center gap-1 rounded border border-line px-1.5 py-0.5">
              <span className="num text-muted">{x.minute}</span>
              {x.type === "red" ? (
                <span className="inline-block h-2.5 w-2 rounded-[1px] bg-critical" aria-label="kırmızı kart" />
              ) : (
                <span aria-label="gol">⚽</span>
              )}
              <span className="max-w-28 truncate">{x.player ?? (x.side === "home" ? item.home.name : item.away.name)}</span>
              {x.type === "own_goal" && <span className="text-muted">(k.k.)</span>}
              {x.type === "penalty" && <span className="text-muted">(p)</span>}
            </li>
          ))}
        </ul>
      )}

      {ms ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="kicker">Canlı model</span>
            {item.pre_ms && (
              <span className="num text-[0.68rem] text-muted">
                maç öncesi {pct(item.pre_ms["1"])} · {pct(item.pre_ms["0"])} · {pct(item.pre_ms["2"])}
              </span>
            )}
          </div>
          <ProbBar ms={ms} />
          <div className="num flex flex-wrap gap-x-3 text-[0.72rem] text-ink-2">
            <span>2.5 Üst <b className="text-ink">{pct(au25)}</b></span>
            <span>KG Var <b className="text-ink">{pct(kg)}</b></span>
            {(s!.redHome > 0 || s!.redAway > 0) && <span className="text-critical-ink">kırmızı kart hesaba katıldı</span>}
          </div>
        </div>
      ) : !s?.started && item.pre_ms ? (
        <ProbBar ms={item.pre_ms} />
      ) : null}

      {item.pick && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wider text-accent">Öneri</span>
          <span className="text-ink-2">
            {marketLine(item.pick.label, item.pick.line)}: <b className="text-ink">{item.pick.name}</b> <span className="num">@{odd(item.pick.odd)}</span>
          </span>
          <StatusChip status={pickStatus(item.pick.key, item.pick.line, item.pick.name, s ?? null)} />
        </div>
      )}

      {rows.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-line">
          <p className="flex items-center justify-between border-b border-line bg-surface-2 px-3 py-1.5 text-[0.68rem] text-muted">
            <span className="font-semibold uppercase tracking-wider">iddaa canlı</span>
            <span>oran · model · EV</span>
          </p>
          <table className="w-full text-xs">
            <tbody className="divide-y divide-line/60">
              {rows.map((r) => (
                <tr key={r.label}>
                  <td className="px-3 py-1.5 text-ink-2">{r.label}</td>
                  {r.outcomes.map((o) => {
                    const ev = o.p != null ? o.p * o.odd - 1 : null;
                    const value = ev != null && o.p != null && ev >= VALUE_EV && o.p >= VALUE_MIN_P && !lowConf;
                    return (
                      <td key={o.name} className={`px-1.5 py-1.5 text-right ${value ? "bg-good/10" : ""}`}>
                        <div className="num font-semibold">
                          {OUT[o.name] ?? o.name} {odd(o.odd)}
                        </div>
                        <div className={`num text-[0.62rem] ${value ? "text-good-ink" : "text-muted"}`}>
                          {pct(o.p)}{ev != null ? ` · ${signedPct(ev, 0)}` : ""}{value ? " ▲" : ""}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s?.started && !s.finished && !il && item.iddaa && <p className="text-[0.7rem] text-muted">Bu maç için iddaa canlı bülteninde oran yok.</p>}
      {scoreMismatch && <p className="text-[0.7rem] text-warn">iddaa ile ESPN skoru farklı görünüyor; kaynaklardan biri gecikmeli.</p>}
    </article>
  );
}
