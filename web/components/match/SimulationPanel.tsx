"use client";

import { useMemo, useState } from "react";
import { isPicked, togglePick, useCoupon } from "@/lib/coupon-store";
import { pct } from "@/lib/format";
import type { DistSummary, MatchDetail, SimPlayer, SimTeam } from "@/lib/types";
import Columns from "../charts/Columns";
import { Crest } from "../ui";
import ScenarioTimeline from "./ScenarioTimeline";

type Side = "home" | "away";
const SIDE_COLOR: Record<Side, string> = { home: "var(--home)", away: "var(--away)" };

function pmfColumns(dist: DistSummary, maxK: number, unit: string) {
  const out = [];
  for (let k = 0; k <= maxK; k++) {
    const y = dist.pmf[String(k)] ?? 0;
    out.push({ x: k === maxK ? `${k}+` : String(k), y, tip: `${k}${k === maxK ? "+" : ""} ${unit}: ${pct(y, 1)}` });
  }
  const tail = Object.entries(dist.pmf).filter(([k]) => Number(k) > maxK).reduce((s, [, v]) => s + v, 0);
  out[maxK].y += tail;
  out[maxK].tip = `${maxK}+ ${unit}: ${pct(out[maxK].y, 1)}`;
  return out;
}

export default function SimulationPanel({ d }: { d: MatchDetail }) {
  const sim = d.sim!;
  const teams: Record<Side, { name: string; logo?: string | null; t: SimTeam }> = {
    home: { name: d.match.home.name, logo: d.match.home.logo, t: sim.teams.home },
    away: { name: d.match.away.name, logo: d.match.away.logo, t: sim.teams.away },
  };
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 md:grid-cols-2">
        {(["home", "away"] as const).map((s) => (
          <TeamSimCard key={s} side={s} name={teams[s].name} logo={teams[s].logo} t={teams[s].t} source={sim.notes.lineup_source[s]} notes={sim.notes[s]} />
        ))}
      </div>
      {sim.scenarios.length > 0 && <ScenarioTimeline d={d} />}
      <PlayerTables d={d} />
      <p className="text-xs leading-relaxed text-muted">
        Süreç: skor Dixon-Coles dağılımından çekilir; şut, isabetli şut ve goller bu skora koşullu üretilir (gol ≤ isabetli
        şut ≤ şut). Kadro, geçmiş maçlardaki ilk 11 ve değişiklik alışkanlıklarından senaryolar halinde örneklenir; resmi
        kadro açıklandıysa o kullanılır. Oyuncu oranları pozisyon ortalamasına doğru büzülür (az veri = temkinli tahmin).
        Sakatlık/ceza verisi kaynakta yok.
      </p>
    </div>
  );
}

function TeamSimCard({ side, name, logo, t, source, notes }: { side: Side; name: string; logo?: string | null; t: SimTeam; source: string; notes: string[] }) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center gap-2">
        <Crest team={{ name, logo: logo ?? null }} size={24} />
        <p className="font-semibold">{name}</p>
        <span className="ml-auto text-xs text-muted">kadro: {source}</span>
      </div>
      <div className="mb-3 grid grid-cols-3 gap-2 text-center">
        <Metric label="Şut (ort.)" value={t.shots.mean.toFixed(1)} sub={`%80 aralık ${t.shots.p10}–${t.shots.p90}`} />
        <Metric label="İsabetli (ort.)" value={t.shots_on_target.mean.toFixed(1)} sub={`%80 aralık ${t.shots_on_target.p10}–${t.shots_on_target.p90}`} />
        <Metric label="İsabet oranı" value={pct(t.u)} sub={`gol/isabet ${pct(t.v)}`} />
      </div>
      <p className="kicker mb-1">İsabetli şut dağılımı · {name}</p>
      <Columns data={pmfColumns(t.shots_on_target, 10, "isabetli şut")} color={SIDE_COLOR[side]} label={`${name} isabetli şut dağılımı`} />
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        {Object.entries(t.shots_on_target.at_least).map(([k, v]) => (
          <span key={k} className="num rounded border border-line px-1.5 py-0.5 text-ink-2">
            {k}+ isabetli <b className="text-ink">{pct(v)}</b>
          </span>
        ))}
      </div>
      {!t.players_available && <p className="mt-2 text-xs text-warn">Oyuncu düzeyi veri yetersiz: yalnızca takım düzeyi simülasyon.</p>}
      {notes.map((n) => (
        <p key={n} className="mt-2 text-xs text-warn">
          {n}
        </p>
      ))}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg bg-surface-2 px-2 py-2">
      <p className="text-[0.65rem] uppercase tracking-wider text-muted">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
      <p className="num text-[0.62rem] text-muted">{sub}</p>
    </div>
  );
}

type SortKey = "exp_shots" | "p_sot_1" | "p_sot_2" | "p_goal" | "p_shots_2" | "exp_minutes";
const COLS: { key: SortKey; label: string; title: string }[] = [
  { key: "exp_minutes", label: "Dk", title: "Beklenen dakika" },
  { key: "exp_shots", label: "Şut", title: "Beklenen şut" },
  { key: "p_shots_2", label: "2+ şut", title: "En az 2 şut olasılığı" },
  { key: "p_sot_1", label: "1+ isabet", title: "En az 1 isabetli şut olasılığı" },
  { key: "p_sot_2", label: "2+ isabet", title: "En az 2 isabetli şut olasılığı" },
  { key: "p_goal", label: "Gol", title: "Gol atma olasılığı" },
];

function PlayerTables({ d }: { d: MatchDetail }) {
  const [side, setSide] = useState<Side>("home");
  const [sort, setSort] = useState<SortKey>("p_sot_1");
  const team = d.sim!.teams[side];
  const rows = useMemo(() => [...team.players].sort((a, b) => b[sort] - a[sort]), [team, sort]);
  const name = side === "home" ? d.match.home.name : d.match.away.name;
  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <p className="font-display text-lg font-extrabold uppercase">Oyuncu projeksiyonları</p>
        <div className="ml-auto flex gap-1" role="tablist">
          {(["home", "away"] as const).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={side === s}
              onClick={() => setSide(s)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm ${side === s ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2"}`}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: SIDE_COLOR[s] }} aria-hidden />
              {s === "home" ? d.match.home.name : d.match.away.name}
            </button>
          ))}
        </div>
      </div>
      {!team.players_available || rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted">{name} için oyuncu düzeyi veri yetersiz.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Oyuncu</th>
                <th className="px-2 py-2 font-medium" title="İlk 11 / oynama olasılığı">İlk 11 · oynar</th>
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
                <PlayerRow key={p.player_id} p={p} color={SIDE_COLOR[side]} d={d} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AddPlayerPick({ d, p, code, label, prob }: { d: MatchDetail; p: SimPlayer; code: string; label: string; prob: number }) {
  const picks = useCoupon();
  const key = `oyuncu:${p.player_id}:${code}`;
  const on = isPicked(picks, d.match.id, key, 0);
  if (prob <= 0.01) return null;
  return (
    <button
      type="button"
      aria-pressed={on}
      title={on ? "Kupondan çıkar" : `Kupona ekle: ${p.name} ${label} (adil oran ${(1 / prob).toFixed(2)})`}
      onClick={() =>
        togglePick({
          match_id: d.match.id, market_key: key, outcome_no: 0, home: d.match.home.name, away: d.match.away.name,
          date_utc: d.match.date_utc, label, line: null, outcome_name: p.name, odd: Math.round((1 / prob) * 100) / 100,
          p_model: prob, p_market: prob, p_safe: prob, ev: 0, mbs: 1, family_validated: true, odds_at: d.created_at,
          has_market: false,
        })
      }
      className={`grid h-5 w-5 place-items-center rounded border text-[0.7rem] ${
        on ? "border-accent bg-accent text-accent-ink" : "border-line text-ink-2 hover:border-accent hover:text-ink"
      }`}
    >
      {on ? "✓" : "+"}
    </button>
  );
}

function PlayerRow({ p, color, d }: { p: SimPlayer; color: string; d: MatchDetail }) {
  return (
    <tr className="hover:bg-surface-2">
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="num w-6 rounded bg-surface-3 text-center text-[0.65rem] text-ink-2">{p.position ?? p.pos_group}</span>
          <span className="font-medium">{p.name}</span>
          {p.confirmed_starter === true && <span className="text-[0.65rem] text-good-ink">✓ ilk 11</span>}
          {p.flags.length > 0 && (
            <span className="cursor-help text-warn" title={p.flags.join(" · ")} aria-label={p.flags.join(" · ")}>
              ⚠
            </span>
          )}
        </div>
        <p className="num mt-0.5 text-[0.65rem] text-muted" title="Büzülmüş oranlar">
          {p.rate_shots_p90.toFixed(2)} şut/90 · isabet {pct(p.rate_acc)} · dönüşüm {pct(p.rate_conv)} · {Math.round(p.minutes_seen)} dk veri
        </p>
      </td>
      <td className="num px-2 py-2 text-ink-2">
        {pct(p.p_start)} · {pct(p.p_play)}
      </td>
      <td className="num px-2 py-2 text-right">{Math.round(p.exp_minutes)}</td>
      <td className="num px-2 py-2 text-right">{p.exp_shots.toFixed(2)}</td>
      <td className="num px-2 py-2 text-right">{pct(p.p_shots_2)}</td>
      <td className="px-2 py-2 text-right">
        <div className="flex items-center justify-end gap-2">
          <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-surface-3 sm:block" aria-hidden>
            <span className="block h-full rounded-full" style={{ width: `${p.p_sot_1 * 100}%`, background: color }} />
          </span>
          <span className="num font-semibold">{pct(p.p_sot_1)}</span>
          <AddPlayerPick d={d} p={p} code="sot1" label="Oyuncu 1+ isabetli şut" prob={p.p_sot_1} />
        </div>
      </td>
      <td className="num px-2 py-2 text-right">{pct(p.p_sot_2)}</td>
      <td className="px-2 py-2 text-right">
        <div className="flex items-center justify-end gap-2">
          <span className="num">{pct(p.p_goal)}</span>
          <AddPlayerPick d={d} p={p} code="goal" label="Oyuncu gol atar" prob={p.p_goal} />
        </div>
      </td>
    </tr>
  );
}
