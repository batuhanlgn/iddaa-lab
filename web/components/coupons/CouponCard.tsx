import Link from "next/link";
import { kickoff, marketLine, odd, pct, signedPct } from "@/lib/format";
import type { GeneratedCoupon, Selection } from "@/lib/types";
import { EvTag } from "../ui";

const ACCENT: Record<GeneratedCoupon["kind"], string> = {
  deger: "var(--good)",
  olasilik: "var(--home)",
  dengeli: "var(--accent)",
  oyuncu: "var(--away)",
};

export function SelectionLine({ s, result }: { s: Selection; result?: string | null }) {
  return (
    <li className="flex items-start gap-3 py-2">
      <div className="min-w-0 flex-1">
        <Link href={`/mac/${s.match_id}`} className="block truncate text-sm font-medium hover:underline">
          {s.home} – {s.away}
        </Link>
        <p className="truncate text-xs text-muted">
          <span className="num">{kickoff(s.date_utc)}</span> · {s.league_name}
        </p>
        <p className="mt-0.5 text-sm text-ink-2">
          {marketLine(s.label, s.line)}: <b className="text-ink">{s.outcome_name}</b>
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="num text-base font-semibold">{odd(s.odd)}</span>
        <span className="num text-[0.68rem] text-muted" title="Model / piyasa / harman olasılığı">
          {pct(s.p_model)} · {pct(s.p_market)} · <b className="text-ink-2">{pct(s.p_blend)}</b>
        </span>
        {result ? (
          <span className={`text-[0.68rem] font-semibold ${result === "won" ? "text-good-ink" : result === "lost" ? "text-critical-ink" : "text-muted"}`}>
            {result === "won" ? "✓ tuttu" : result === "lost" ? "✕ yattı" : "↺ iade"}
          </span>
        ) : s.ev != null ? (
          <EvTag ev={s.ev} validated={s.family_validated !== false} />
        ) : (
          <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] text-muted" title="iddaa bülteninde bu pazar yok">
            adil oran
          </span>
        )}
        {s.family_validated === false && <span className="text-[0.62rem] text-warn">doğrulanmamış pazar</span>}
      </div>
    </li>
  );
}

export default function CouponCard({ c, delay = 0 }: { c: GeneratedCoupon; delay?: number }) {
  return (
    <article className="panel rise relative flex flex-col overflow-hidden" style={{ animationDelay: `${delay}ms` }}>
      <div className="h-1 w-full" style={{ background: ACCENT[c.kind] }} aria-hidden />
      <div className="flex flex-col gap-1 px-4 pt-4">
        <div className="flex items-center gap-2">
          <h3 className="font-display text-2xl font-black uppercase leading-none">{c.title}</h3>
          {c.experimental && (
            <span className="rounded border border-warn/50 px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wider text-warn" title="Model-piyasa harmanı henüz ileriye dönük doğrulanmadı">
              ⚠ deneysel
            </span>
          )}
        </div>
        <p className="text-xs leading-relaxed text-muted">{c.description}</p>
      </div>
      {c.selections.length === 0 ? (
        <div className="m-4 rounded-lg border border-dashed border-line-strong px-4 py-6 text-center text-sm text-ink-2">
          {c.empty_reason ?? "Uygun seçim yok."}
        </div>
      ) : (
        <>
          <ul className="mx-4 mt-2 divide-y divide-line">
            {c.selections.map((s) => (
              <SelectionLine key={`${s.match_id}-${s.market_key}-${s.outcome_no}`} s={s} />
            ))}
          </ul>
          <div className="mt-auto grid grid-cols-3 gap-2 border-t border-line bg-surface-2 px-4 py-3 text-center">
            <div>
              <p className="kicker">Toplam oran</p>
              <p className="num text-xl font-semibold">{odd(c.total_odds)}</p>
            </div>
            <div>
              <p className="kicker">Tutma olasılığı</p>
              <p className="num text-xl font-semibold">{pct(c.prob, 1)}</p>
            </div>
            <div>
              <p className="kicker">Beklenen değer</p>
              {c.ev != null ? (
                <p className={`num text-xl font-semibold ${c.ev >= 0 ? "text-good-ink" : "text-critical-ink"}`}>
                  {c.ev >= 0 ? "▲" : "▼"} {signedPct(c.ev)}
                </p>
              ) : (
                <p className="text-sm text-muted">oran yok</p>
              )}
            </div>
          </div>
          <div className="px-4 pb-3 pt-2 text-[0.68rem] leading-relaxed text-muted">
            Olasılık, seçimlerin bağımsız olduğu varsayımıyla çarpılarak bulunur. MBS gereği: {c.mbs_required}{" "}
            {c.mbs_ok ? "✓" : "✕"}
            {c.warnings.map((w) => (
              <p key={w} className="text-warn">
                {w}
              </p>
            ))}
          </div>
        </>
      )}
    </article>
  );
}
