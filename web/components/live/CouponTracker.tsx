"use client";

import Link from "next/link";
import { useCoupon } from "@/lib/coupon-store";
import { kickoff, marketLine, odd, pct } from "@/lib/format";
import type { EspnLive, LiveBaseItem, PlayerLive } from "@/lib/live-feed";
import { pickLiveProb, pickStatus, type PickStatus } from "@/lib/live-model";
import type { GeneratedCoupon } from "@/lib/types";
import { KIND } from "../coupons/CouponHistory";
import { EmptyState } from "../ui";
import StatusChip from "./StatusChip";

export interface TrackSel {
  match_id: string;
  home: string;
  away: string;
  date_utc: string;
  key: string;
  market_key: string;
  label: string;
  line: string | null;
  name: string;
  odd: number;
}

const PLAYER_NEED: Record<string, [keyof PlayerLive, number]> = {
  sot1: ["sot", 1], sot2: ["sot", 2], shots2: ["shots", 2], shots3: ["shots", 3], goal: ["goals", 1],
};

function playerStatus(sel: TrackSel, e: EspnLive | undefined, stats: Map<string, PlayerLive> | undefined): PickStatus {
  if (!e || !e.state.started) return "bekliyor";
  const [, pid, code] = sel.market_key.split(":");
  const need = PLAYER_NEED[code];
  const p = stats?.get(pid);
  if (!need) return "takip yok";
  if (!p) return e.state.finished ? "yattı" : "tutmuyor";
  const v = Number(p[need[0]]);
  if (v >= need[1]) return "tuttu";
  return e.state.finished ? (p.played ? "yattı" : "takip yok") : "tutmuyor";
}

export function selStatus(sel: TrackSel, espn: Map<string, EspnLive>, players: Map<string, Map<string, PlayerLive>>): PickStatus {
  const e = espn.get(sel.match_id);
  if (sel.key === "oyuncu") return playerStatus(sel, e, players.get(sel.match_id));
  return pickStatus(sel.key, sel.line, sel.name, e?.state ?? null);
}

function CouponBlock({
  title, sels, espn, players, base, badge,
}: {
  title: string;
  sels: TrackSel[];
  espn: Map<string, EspnLive>;
  players: Map<string, Map<string, PlayerLive>>;
  base: Map<string, LiveBaseItem>;
  badge?: string;
}) {
  const statuses = sels.map((s) => selStatus(s, espn, players));
  const lost = statuses.filter((x) => x === "yattı").length;
  const won = statuses.filter((x) => x === "tuttu").length;
  // Kupon canlı olasılığı (bağımsızlık varsayımıyla): tutanlar 1, yatanlar 0, diğerleri canlı modelden
  let prob: number | null = 1;
  for (let i = 0; i < sels.length; i++) {
    const st = statuses[i];
    if (st === "yattı") { prob = 0; break; }
    if (st === "tuttu") continue;
    const it = base.get(sels[i].match_id);
    const e = espn.get(sels[i].match_id);
    const p = sels[i].key === "oyuncu" ? null
      : e?.state.started ? pickLiveProb(sels[i].key, sels[i].line, sels[i].name, it?.model ?? null, e.state)
      : null;
    if (p == null) { prob = null; break; }
    prob *= p;
  }
  const overall = lost > 0 ? "Kupon yattı" : won === sels.length ? "Kupon tuttu" : `${won}/${sels.length} kesinleşti`;
  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <p className="font-display text-lg font-extrabold uppercase">
          {title}
          {badge && <span className="ml-2 align-middle text-[0.65rem] font-semibold normal-case text-warn">{badge}</span>}
        </p>
        <span className={`text-xs font-semibold ${lost ? "text-critical-ink" : won === sels.length ? "text-good-ink" : "text-ink-2"}`}>
          {overall}
          {prob != null && lost === 0 && won < sels.length ? ` · şu an tutma olasılığı ${pct(prob)}` : ""}
        </span>
      </div>
      <ul className="divide-y divide-line">
        {sels.map((s, i) => {
          const e = espn.get(s.match_id);
          const it = base.get(s.match_id);
          const p = s.key !== "oyuncu" && e?.state.started && !e.state.finished
            ? pickLiveProb(s.key, s.line, s.name, it?.model ?? null, e.state) : null;
          return (
            <li key={`${s.match_id}-${s.market_key}-${s.name}`} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <Link href={`/mac/${s.match_id}`} className="truncate font-medium hover:underline">
                  {s.home} – {s.away}
                </Link>
                <p className="text-xs text-muted">
                  {e?.state.started ? (
                    <span className="num font-semibold text-ink-2">{e.state.home}-{e.state.away} {e.state.finished ? "MS" : e.clock}</span>
                  ) : (
                    <span className="num">{kickoff(s.date_utc)}</span>
                  )}{" "}
                  · {marketLine(s.label, s.line)}: <b className="text-ink-2">{s.name}</b> <span className="num">@{odd(s.odd)}</span>
                </p>
              </div>
              {p != null && <span className="num text-xs text-muted" title="Canlı modele göre maç sonunda tutma olasılığı">{pct(p)}</span>}
              <StatusChip status={statuses[i]} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function CouponTracker({
  coupons, espn, players, base,
}: {
  coupons: GeneratedCoupon[];
  espn: Map<string, EspnLive>;
  players: Map<string, Map<string, PlayerLive>>;
  base: Map<string, LiveBaseItem>;
}) {
  const picks = useCoupon();
  const mine: TrackSel[] = picks.map((p) => ({
    match_id: p.match_id, home: p.home, away: p.away, date_utc: p.date_utc,
    key: p.market_key.startsWith("oyuncu:") ? "oyuncu" : keyFromLabel(p.market_key),
    market_key: p.market_key, label: p.label, line: p.line, name: p.outcome_name, odd: p.odd,
  }));
  const model = coupons.filter((c) => c.selections.length > 0);
  if (mine.length === 0 && model.length === 0) {
    return <EmptyState title="Takip edilecek kupon yok">Kendi kuponuna seçim ekle ya da model kuponlarının üretilmesini bekle.</EmptyState>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {mine.length > 0 && <CouponBlock title="Kendi kuponun" sels={mine} espn={espn} players={players} base={base} />}
      {model.map((c) => (
        <CouponBlock
          key={c.kind}
          title={KIND[c.kind] ?? c.title}
          badge={c.experimental ? "deneysel" : undefined}
          sels={c.selections.map((s) => ({
            match_id: s.match_id, home: s.home, away: s.away, date_utc: s.date_utc, key: s.key, market_key: s.market_key,
            label: s.label, line: s.line, name: s.outcome_name, odd: s.odd,
          }))}
          espn={espn}
          players={players}
          base={base}
        />
      ))}
    </div>
  );
}

// Kullanıcı kuponundaki seçimler pazar anahtarını "t:st:sov" biçiminde saklar; iç pazar adına çevir
const ST_KEY: Record<string, string> = {
  "1:1": "ms", "2:92": "cs", "2:88": "iy", "2:36": "iy2", "2:77": "iy_cs", "2:89": "kg", "2:720": "iy_kg", "2:101": "au",
  "2:60": "iy_au", "2:603": "ev_au", "2:604": "dep_au", "2:100": "hnd", "2:90": "iyms", "2:91": "tc", "2:4": "tg",
  "2:6": "cgy", "2:7": "ms_au", "2:698": "ms_kg", "2:700": "au_kg", "2:48": "korner_au",
};

function keyFromLabel(marketKey: string): string {
  const [t, st] = marketKey.split(":");
  return ST_KEY[`${t}:${st}`] ?? "bilinmiyor";
}
