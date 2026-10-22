import { dateTime, odd, pct, signedPct } from "@/lib/format";
import type { CouponHistoryResponse } from "@/lib/types";
import { EmptyState } from "../ui";
import { SelectionLine } from "./CouponCard";

export const KIND: Record<string, string> = {
  deger: "Değer", olasilik: "Yüksek olasılık", dengeli: "Dengeli", oyuncu: "Oyuncu", tekli: "Tekli",
  sistem_2_3: "Sistem 2/3", sistem_3_4: "Sistem 3/4", surpriz: "Sürpriz", korner: "Korner", kart: "Kart",
};
const STATUS: Record<string, { label: string; cls: string }> = {
  open: { label: "● açık", cls: "text-ink-2" },
  won: { label: "✓ tuttu", cls: "text-good-ink" },
  lost: { label: "✕ yattı", cls: "text-critical-ink" },
  void: { label: "↺ iade", cls: "text-muted" },
};

export default function CouponHistory({ data }: { data: CouponHistoryResponse }) {
  if (data.items.length === 0) {
    return (
      <EmptyState title="Henüz kupon arşivi yok">
        Model kuponları her güncellemede zaman damgasıyla arşivlenir; maçlar bitince otomatik sonuçlandırılır ve buradaki
        isabet/ROI tablosu dolar.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(data.summary).map(([k, s]) => (
          <div key={k} className="panel p-4">
            <p className="kicker">{KIND[k] ?? k}</p>
            <p className="mt-1 text-2xl font-semibold">
              {s.won}/{s.settled} <span className="text-sm font-normal text-muted">tuttu</span>
            </p>
            <p className="text-xs text-ink-2">
              Beklenen isabet <span className="num">{s.expected_hits.toFixed(1)}</span> · ROI{" "}
              <span className={`num font-semibold ${s.roi == null ? "" : s.roi >= 0 ? "text-good-ink" : "text-critical-ink"}`}>
                {s.roi == null ? "–" : signedPct(s.roi)}
              </span>{" "}
              · {s.n - s.settled} açık
            </p>
          </div>
        ))}
      </div>
      <div className="panel divide-y divide-line">
        {data.items.slice(0, 30).map((c) => (
          <details key={c.id} className="group px-4 py-3">
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 text-sm">
              <span className={`w-20 font-semibold ${STATUS[c.status].cls}`}>{STATUS[c.status].label}</span>
              <span className="text-ink-2">
                {KIND[c.kind] ?? c.kind}
                {c.experimental && <span className="ml-1.5 text-[0.65rem] uppercase text-warn">⚠ deneysel</span>}
              </span>
              <span className="num text-muted">{dateTime(c.created_at)}</span>
              <span className="num ml-auto">
                {c.selections.length} seçim · oran <b>{odd(c.total_odds)}</b> · olasılık {pct(c.prob, 1)}
              </span>
              <span className="text-muted transition-transform group-open:rotate-90" aria-hidden>
                ›
              </span>
            </summary>
            <ul className="mt-2 divide-y divide-line">
              {c.selections.map((s, i) => (
                <SelectionLine key={`${s.match_id}-${s.market_key}-${s.outcome_no}`} s={s} result={c.selection_results?.[i] ?? null} />
              ))}
            </ul>
          </details>
        ))}
      </div>
    </div>
  );
}
