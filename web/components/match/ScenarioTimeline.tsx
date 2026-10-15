"use client";

import { useState } from "react";
import type { MatchDetail, SimEvent } from "@/lib/types";

const LABEL: Record<SimEvent["type"], string> = {
  goal: "GOL",
  own_goal_for: "Kendi kalesine gol",
  sot: "İsabetli şut",
  shot: "İsabetsiz şut",
  sub_in: "Oyuna girdi",
};

/** Modelden örnek senaryo: dakika ekseni, ev olayları üstte, deplasman altta. Saha koordinatı uydurulmaz. */
export default function ScenarioTimeline({ d }: { d: MatchDetail }) {
  const scenarios = d.sim!.scenarios;
  const [idx, setIdx] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const sc = scenarios[idx];
  const W = 900;
  const H = 170;
  const mid = H / 2;
  const x = (m: number) => 24 + (Math.min(m, 90) / 90) * (W - 48);

  // Aynı dakikadaki olayları dikeyde istifle (çakışmayı önle)
  const counts = new Map<string, number>();
  const placed = sc.events.map((e) => {
    const k = `${e.side}-${e.minute}`;
    const n = counts.get(k) ?? 0;
    counts.set(k, n + 1);
    const dir = e.side === "home" ? -1 : 1;
    return { e, cx: x(e.minute), cy: mid + dir * (18 + n * 13) };
  });
  const goalsFeed = sc.events
    .filter((e) => e.type === "goal" || e.type === "own_goal_for")
    .reduce<{ e: SimEvent; h: number; a: number }[]>((acc, e) => {
      const prev = acc[acc.length - 1] ?? { h: 0, a: 0 };
      acc.push({ e, h: prev.h + (e.side === "home" ? 1 : 0), a: prev.a + (e.side === "away" ? 1 : 0) });
      return acc;
    }, []);

  return (
    <div className="panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div>
          <p className="kicker">Modelden örnek senaryo {idx + 1} / {scenarios.length}</p>
          <p className="font-display text-2xl font-black uppercase">
            {d.match.home.name} <span className="num">{sc.score[0]}–{sc.score[1]}</span> {d.match.away.name}
            <span className="num ml-2 text-sm font-normal normal-case text-muted">(İY {sc.ht[0]}–{sc.ht[1]})</span>
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-ink-2">
          <span className="num">
            Şut {sc.stats.home.shots}–{sc.stats.away.shots} · İsabetli {sc.stats.home.sot}–{sc.stats.away.sot}
          </span>
          <button
            type="button"
            onClick={() => setIdx((idx + 1) % scenarios.length)}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink hover:opacity-90"
          >
            Başka senaryo ↻
          </button>
        </div>
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Örnek maç akışı zaman çizelgesi">
          <rect x={x(0)} y={mid - 0.5} width={x(90) - x(0)} height={1} fill="var(--line-strong)" />
          <line x1={x(45)} x2={x(45)} y1={10} y2={H - 10} stroke="var(--grid)" strokeWidth="1" />
          {[0, 15, 30, 45, 60, 75, 90].map((m) => (
            <text key={m} x={x(m)} y={mid + 4} textAnchor="middle" fontSize="9" fill="var(--muted)" className="num" style={{ paintOrder: "stroke" }} stroke="var(--surface)" strokeWidth={4}>
              {m}&apos;
            </text>
          ))}
          <text x={4} y={16} fontSize="10" fill="var(--ink-2)">{d.match.home.short_name ?? d.match.home.name}</text>
          <text x={4} y={H - 6} fontSize="10" fill="var(--ink-2)">{d.match.away.short_name ?? d.match.away.name}</text>
          {placed.map(({ e, cx, cy }, i) => {
            const color = e.side === "home" ? "var(--home)" : "var(--away)";
            const on = hover === i;
            return (
              <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
                <circle cx={cx} cy={cy} r={11} fill="transparent" />
                {e.type === "goal" || e.type === "own_goal_for" ? (
                  <circle cx={cx} cy={cy} r={on ? 8 : 6.5} fill={color} stroke="var(--surface)" strokeWidth={2} />
                ) : e.type === "sot" ? (
                  <circle cx={cx} cy={cy} r={on ? 5.5 : 4.5} fill="var(--surface)" stroke={color} strokeWidth={2} />
                ) : e.type === "shot" ? (
                  <line x1={cx - 3} x2={cx + 3} y1={cy - 3} y2={cy + 3} stroke={color} strokeWidth={2} strokeLinecap="round" opacity={0.75} />
                ) : (
                  <path d={`M${cx - 4},${cy} L${cx + 3},${cy} M${cx},${cy - 3} L${cx + 3},${cy} L${cx},${cy + 3}`} stroke="var(--muted)" strokeWidth={1.5} fill="none" />
                )}
              </g>
            );
          })}
        </svg>
        {hover != null && placed[hover] && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-line bg-surface-3 px-2 py-1 text-xs shadow-lg"
            style={{ left: `${(placed[hover].cx / W) * 100}%`, top: `${(placed[hover].cy / H) * 100}%` }}
          >
            <b className="num">{placed[hover].e.minute}&apos;</b> {LABEL[placed[hover].e.type]}
            {placed[hover].e.player ? ` · ${placed[hover].e.player}` : ""}
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-ink-2">
        <span className="flex items-center gap-1"><svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="5" fill="var(--ink-2)" /></svg> Gol</span>
        <span className="flex items-center gap-1"><svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="4" fill="none" stroke="var(--ink-2)" strokeWidth="2" /></svg> İsabetli şut</span>
        <span className="flex items-center gap-1"><svg width="12" height="12" aria-hidden><line x1="3" x2="9" y1="3" y2="9" stroke="var(--ink-2)" strokeWidth="2" /></svg> İsabetsiz şut</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: "var(--home)" }} /> {d.match.home.name}</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: "var(--away)" }} /> {d.match.away.name}</span>
      </div>
      {goalsFeed.length > 0 && (
        <ol className="mt-3 flex flex-wrap gap-2 text-sm">
          {goalsFeed.map(({ e, h, a }, i) => (
            <li key={i} className="num rounded-md border border-line bg-surface-2 px-2 py-1">
              {e.minute}&apos; <b>{h}–{a}</b> {e.player ?? (e.type === "own_goal_for" ? "kendi kalesine" : "")}
            </li>
          ))}
        </ol>
      )}
      <p className="mt-2 text-[0.7rem] text-muted">
        Bu, binlerce simülasyondan yalnızca biri; dakikalar oyuncunun sahada olduğu aralıktan örneklenir. Tahmin değil, olası
        bir maç akışı örneğidir.
      </p>
    </div>
  );
}
