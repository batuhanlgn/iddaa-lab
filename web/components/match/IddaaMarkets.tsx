"use client";

import { useMemo, useState } from "react";
import { isPicked, togglePick, useCoupon } from "@/lib/coupon-store";
import { dateTime, lineText, odd, pct } from "@/lib/format";
import type { IddaaMarket, MatchDetail } from "@/lib/types";
import { EvTag } from "../ui";

const FAMILY_LABEL: Record<string, string> = {
  ms: "Sonuç", au: "Gol", kg: "Karşılıklı gol", iy: "İlk yarı", korner: "Korner", kart: "Kart",
};

export default function IddaaMarkets({ d }: { d: MatchDetail }) {
  const markets = d.iddaa!.markets;
  const families = useMemo(() => [...new Set(markets.map((m) => m.family))], [markets]);
  const [fam, setFam] = useState<string>("all");
  const [storageError, setStorageError] = useState(false);
  const picks = useCoupon();
  const shown = fam === "all" ? markets : markets.filter((m) => m.family === fam);
  const fetched = markets[0]?.fetched_at;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {["all", ...families].map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFam(f)}
            className={`rounded-md px-2.5 py-1 text-sm ${fam === f ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2"}`}
          >
            {f === "all" ? "Tümü" : (FAMILY_LABEL[f] ?? f)}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted">
          Oranlar: iddaa.com · {dateTime(fetched)} · Harman ağırlığı (model) {pct(d.model?.blend_weight ?? 0.5)}
          {d.model?.blend_calibrated ? " · kalibre" : " · varsayılan (arşiv birikiyor)"}
        </span>
      </div>
      {storageError && (
        <p role="alert" className="text-sm text-critical-ink">
          Kupon bu tarayıcıda kaydedilemedi (depolama kapalı olabilir).
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {shown.map((m) => (
          <MarketCard
            key={m.market_key}
            m={m}
            d={d}
            picked={(no) => isPicked(picks, d.match.id, m.market_key, no)}
            onPick={(no) => {
              const o = m.outcomes.find((x) => x.no === no)!;
              const pSafe = o.p_safe ?? o.p_model;
              const ok = togglePick({
                match_id: d.match.id, market_key: m.market_key, outcome_no: no, home: d.match.home.name, away: d.match.away.name,
                date_utc: d.match.date_utc, label: m.label, line: m.line, outcome_name: o.name, odd: o.odd,
                p_model: o.p_model, p_market: o.p_market, p_safe: pSafe, ev: o.ev ?? pSafe * o.odd - 1,
                mbs: m.mbs ?? 1, family_validated: m.family_validated, odds_at: m.fetched_at,
              });
              setStorageError(!ok);
            }}
          />
        ))}
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Model: skor modelinden olasılık · Piyasa: iddaa oranından marjı orantısal arındırılmış olasılık · EV, harman olasılığı
        × oran − 1&apos;dir. Harman, iddaa&apos;nın ana pazarlarına uydurulan &quot;piyasa skor matrisi&quot; ile model skor matrisinin
        hücre bazında geometrik ortalamasıdır; bu yüzden tüm pazarlar birbiriyle tutarlıdır. Korner ve kart pazarları skor
        modelinden bağımsızdır: takım başına sayım modelinden gelir ve harman pazar içinde yapılır (oranlar maç detayından,
        birkaç saatte bir). Tek yönlü sunulan pazarda (ör. yalnız &quot;Kırmızı kart: Evet&quot;) piyasa olasılığı marjlı 1/orandır.
        Soluk etiketli pazarlar backtest doğrulamasından geçmedi; otomatik kuponlarda yalnız korner/kart kuponuna
        &quot;deneysel&quot; etiketiyle girer.
      </p>
    </div>
  );
}

function MarketCard({ m, d, picked, onPick }: { m: IddaaMarket; d: MatchDetail; picked: (no: number) => boolean; onPick: (no: number) => void }) {
  return (
    <div className={`panel overflow-hidden ${m.family_validated ? "" : "opacity-80"}`}>
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <p className="text-sm font-semibold">
          {m.label}
          {m.line ? <span className="num ml-1 text-ink-2">{lineText(m.key, m.line)}</span> : null}
        </p>
        <div className="flex items-center gap-2 text-[0.68rem] text-muted">
          <span title="Bahis marjı">marj {pct(m.margin, 1)}</span>
          {m.mbs != null && <span>MBS {m.mbs}</span>}
          {!m.family_validated && <span className="rounded border border-line px-1">doğrulanmadı</span>}
        </div>
      </div>
      <table className="w-full text-sm">
        <thead className="text-[0.68rem] text-muted">
          <tr>
            <th className="px-3 py-1 text-left font-medium">Sonuç</th>
            <th className="px-1 py-1 text-right font-medium">Oran</th>
            <th className="px-1 py-1 text-right font-medium" title="Model olasılığı">Model</th>
            <th className="px-1 py-1 text-right font-medium" title="Piyasa (iddaa) olasılığı">Piyasa</th>
            <th className="px-2 py-1 text-right font-medium">EV</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {m.outcomes.map((o) => {
            const on = picked(o.no);
            return (
              <tr key={o.no} className={`border-t border-line/60 ${on ? "bg-accent/10" : ""}`}>
                <td className="max-w-32 truncate px-3 py-1.5" title={o.name}>
                  {outcomeLabel(o.name, d)}
                </td>
                <td className="num px-1 py-1.5 text-right font-semibold">{odd(o.odd)}</td>
                <td className="num px-1 py-1.5 text-right">{pct(o.p_model)}</td>
                <td className="num px-1 py-1.5 text-right text-ink-2">{pct(o.p_market)}</td>
                <td className="px-2 py-1.5 text-right">
                  {o.ev != null ? <EvTag ev={o.ev} validated={m.family_validated} /> : <span className="text-xs text-muted" title="Piyasa skor matrisi kurulamadı">–</span>}
                </td>
                <td className="pr-2">
                  <button
                    type="button"
                    onClick={() => onPick(o.no)}
                    aria-pressed={on}
                    aria-label={on ? "Kupondan çıkar" : "Kupona ekle"}
                    title={on ? "Kupondan çıkar" : "Kupona ekle"}
                    className={`grid h-6 w-6 place-items-center rounded border text-sm ${
                      on ? "border-accent bg-accent text-accent-ink" : "border-line text-ink-2 hover:border-accent hover:text-ink"
                    }`}
                  >
                    {on ? "✓" : "+"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function outcomeLabel(name: string, d: MatchDetail): string {
  if (name === "1") return `1 · ${d.match.home.short_name ?? d.match.home.name}`;
  if (name === "2") return `2 · ${d.match.away.short_name ?? d.match.away.name}`;
  if (name === "0") return "X · Beraberlik";
  return name.replaceAll(" ve 0", " ve X").replace(/^0 ve/, "X ve").replace(/^0\//, "X/").replace(/\/0$/, "/X");
}
