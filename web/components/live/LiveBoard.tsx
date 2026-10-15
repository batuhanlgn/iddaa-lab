"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { dateTime, kickoff } from "@/lib/format";
import {
  fetchEspn, fetchIddaaLive, fetchPlayerStats, matchIddaa,
  type EspnLive, type IddaaLive, type LiveBase, type LiveBaseItem, type PlayerLive,
} from "@/lib/live-feed";
import type { GeneratedCoupon } from "@/lib/types";
import { EmptyState, SectionTitle } from "../ui";
import CouponTracker from "./CouponTracker";
import LiveMatchCard from "./LiveMatchCard";

const POLL_MS = 20_000;
const PLAYER_EVERY = 3; // oyuncu istatistikleri her 3 turda bir (60 sn)

interface FeedState {
  espn: Map<string, EspnLive>;
  iddaa: IddaaLive[];
  players: Map<string, Map<string, PlayerLive>>;
  updatedAt: number | null;
  espnError: string | null;
  iddaaError: string | null;
}

export default function LiveBoard({ base, coupons }: { base: LiveBase; coupons: GeneratedCoupon[] }) {
  const [feed, setFeed] = useState<FeedState>({
    espn: new Map(), iddaa: [], players: new Map(), updatedAt: null, espnError: null, iddaaError: null,
  });
  const [now, setNow] = useState<number>(() => Date.parse(base.generated_at));
  const [busy, setBusy] = useState(false);
  const tick = useRef(0);
  const runRef = useRef<() => void>(() => undefined);

  const baseMap = useMemo(() => new Map(base.items.map((i) => [i.id, i])), [base.items]);
  // Oyuncu seçimlerinin maçları (model oyuncu kuponu + kullanıcı kuponu, kullanıcınınkiler istemcide eklenir)
  const playerMatches = useMemo(() => {
    const ids = new Set<string>();
    for (const c of coupons) for (const s of c.selections) if (s.key === "oyuncu") ids.add(s.match_id);
    return ids;
  }, [coupons]);

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    const run = async () => {
      setBusy(true);
      const t = Date.now();
      // Takip penceresi: 3,5 saat önce başlamış .. 15 dk içinde başlayacak (kupon takibi için 14 saate kadar)
      const window = base.items.filter((i) => {
        const k = Date.parse(i.date_utc);
        return k <= t + 15 * 60_000 && k >= t - 14 * 3600_000;
      });
      const [espnRes, iddaaRes] = await Promise.allSettled([fetchEspn(window, ctrl.signal), fetchIddaaLive(ctrl.signal)]);
      let players: Map<string, Map<string, PlayerLive>> | null = null;
      if (tick.current % PLAYER_EVERY === 0 && espnRes.status === "fulfilled") {
        const live = [...playerMatches].filter((id) => espnRes.value.get(id)?.state.started);
        const got = await Promise.allSettled(
          live.map(async (id) => [id, await fetchPlayerStats(baseMap.get(id)?.league ?? "", id, ctrl.signal)] as const),
        );
        players = new Map(got.flatMap((g) => (g.status === "fulfilled" ? [g.value] : [])));
      }
      tick.current += 1;
      if (!alive) return;
      setFeed((prev) => ({
        espn: espnRes.status === "fulfilled" ? espnRes.value : prev.espn,
        iddaa: iddaaRes.status === "fulfilled" ? iddaaRes.value : prev.iddaa,
        players: players ?? prev.players,
        updatedAt: Date.now(),
        espnError: espnRes.status === "rejected" ? "Canlı skorlar alınamadı (ESPN). Bir sonraki turda tekrar denenecek." : null,
        iddaaError: iddaaRes.status === "rejected" ? "iddaa canlı oranları alınamadı. Bir sonraki turda tekrar denenecek." : null,
      }));
      setNow(Date.now());
      setBusy(false);
    };
    runRef.current = () => void run();
    const first = setTimeout(() => void run(), 0);
    const iv = setInterval(() => void run(), POLL_MS);
    return () => {
      alive = false;
      ctrl.abort();
      clearTimeout(first);
      clearInterval(iv);
    };
  }, [base.items, baseMap, playerMatches]);

  const live: LiveBaseItem[] = [];
  const upcoming: LiveBaseItem[] = [];
  const finished: LiveBaseItem[] = [];
  for (const it of base.items) {
    const e = feed.espn.get(it.id);
    const k = Date.parse(it.date_utc);
    if (e?.state.finished) finished.push(it);
    else if (e?.state.started) live.push(it);
    else if (k > now - 30 * 60_000 && k <= now + 3 * 3600_000) upcoming.push(it);
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="panel flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
        <span className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${busy ? "animate-pulse bg-warn" : "bg-good"}`} aria-hidden />
          {feed.updatedAt ? `Son güncelleme ${dateTime(new Date(feed.updatedAt).toISOString())}` : "Canlı veri yükleniyor…"}
        </span>
        <span className="text-xs text-muted">20 saniyede bir kendiliğinden yenilenir · skor: ESPN · oran: iddaa canlı bülten</span>
        <button
          type="button"
          onClick={() => runRef.current()}
          disabled={busy}
          className="ml-auto rounded-md border border-line-strong px-3 py-1.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-50"
        >
          Şimdi yenile
        </button>
        {(feed.espnError || feed.iddaaError) && (
          <p role="alert" className="w-full text-xs text-critical-ink">
            {[feed.espnError, feed.iddaaError].filter(Boolean).join(" ")}
          </p>
        )}
      </div>

      <section>
        <SectionTitle right={<span className="kicker">{live.length} maç</span>}>Şu an oynananlar</SectionTitle>
        {live.length === 0 ? (
          <EmptyState title={feed.updatedAt ? "Şu an oynanan maç yok" : "Yükleniyor"}>
            {upcoming[0] ? `Sıradaki: ${upcoming[0].home.name} – ${upcoming[0].away.name}, ${kickoff(upcoming[0].date_utc)}` : "Önümüzdeki 3 saatte model kapsamında maç yok."}
          </EmptyState>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {live.map((it) => (
              <LiveMatchCard key={it.id} item={it} espn={feed.espn.get(it.id)} il={matchIddaa(it, feed.iddaa)} />
            ))}
          </div>
        )}
        <p className="mt-2 text-xs leading-relaxed text-muted">
          Canlı model: maç öncesi beklenen goller kalan süreye göre ölçeklenir, anlık skora eklenir; kırmızı kart cezalı takımın gol
          hızını ~%33 düşürür, rakibinkini ~%25 artırır. Yeşil hücreler modelin canlı oranda değer gördüğü seçimlerdir (EV ≥ %5,
          olasılık ≥ %25) — deneysel; sakatlık, oyun üstünlüğü gibi maç içi bilgileri görmez.
        </p>
      </section>

      <section>
        <SectionTitle right={<span className="kicker">canlı durum</span>}>Kupon takibi</SectionTitle>
        <CouponTracker coupons={coupons} espn={feed.espn} players={feed.players} base={baseMap} />
      </section>

      {upcoming.length > 0 && (
        <section>
          <SectionTitle right={<span className="kicker">3 saat içinde</span>}>Yakında başlayacak</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {upcoming.slice(0, 12).map((it) => (
              <LiveMatchCard key={it.id} item={it} espn={feed.espn.get(it.id)} il={null} />
            ))}
          </div>
        </section>
      )}

      {finished.length > 0 && (
        <section>
          <SectionTitle right={<span className="kicker">son 14 saat</span>}>Biten maçlar</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {finished.map((it) => (
              <LiveMatchCard key={it.id} item={it} espn={feed.espn.get(it.id)} il={null} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
