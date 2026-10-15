"use client";

import Link from "next/link";
import { clearPicks, evaluate, removePick, useCoupon } from "@/lib/coupon-store";
import { dateTime, kickoff, marketLine, odd, pct, signedPct } from "@/lib/format";
import { EmptyState } from "../ui";

export default function CouponBuilder() {
  const picks = useCoupon();

  if (picks.length === 0) {
    return (
      <EmptyState title="Kuponun boş" action={<Link href="/" className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink">Bültene git</Link>}>
        Bir maç sayfasındaki iddaa pazarlarında <b>+</b> düğmesiyle seçim ekle. Toplam oran, tutma olasılığı ve beklenen değer
        burada hesaplanır.
      </EmptyState>
    );
  }

  const e = evaluate(picks);
  const oldest = picks.reduce((a, p) => (p.odds_at < a ? p.odds_at : a), picks[0].odds_at);
  return (
    <div className="panel overflow-hidden">
      <ul className="divide-y divide-line">
        {picks.map((p) => (
          <li key={`${p.match_id}-${p.market_key}-${p.outcome_no}`} className="flex items-center gap-3 px-4 py-2.5">
            <div className="min-w-0 flex-1">
              <Link href={`/mac/${p.match_id}`} className="truncate text-sm font-medium hover:underline">
                {p.home} – {p.away}
              </Link>
              <p className="text-xs text-muted">
                <span className="num">{kickoff(p.date_utc)}</span> · {marketLine(p.label, p.line)}: <b className="text-ink-2">{p.outcome_name}</b>
                {!p.family_validated && <span className="ml-1 text-warn">· doğrulanmamış pazar</span>}
              </p>
            </div>
            <div className="text-right">
              <p className="num font-semibold">{odd(p.odd)}</p>
              <p className="num text-[0.68rem] text-muted">
                {pct(p.p_safe)} · {p.has_market === false ? "adil oran" : `EV ${signedPct(p.ev)}`}
              </p>
            </div>
            <button
              type="button"
              onClick={() => removePick(p.match_id)}
              aria-label="Seçimi kaldır"
              className="grid h-7 w-7 place-items-center rounded border border-line text-ink-2 hover:border-critical hover:text-critical-ink"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-4 border-t border-line bg-surface-2 px-4 py-3">
        <Figure label="Toplam oran" value={odd(e.total_odds)} />
        <Figure label="Tutma olasılığı" value={pct(e.prob, 1)} />
        {e.ev != null ? (
          <Figure label="Beklenen değer" value={`${e.ev >= 0 ? "▲" : "▼"} ${signedPct(e.ev)}`} tone={e.ev >= 0 ? "good" : "bad"} />
        ) : (
          <Figure label="Beklenen değer" value="–" />
        )}
        <span className={`text-xs ${e.mbs_ok ? "text-ink-2" : "text-warn"}`}>
          MBS {e.mbs_required} {e.mbs_ok ? "✓ sağlanıyor" : "✕ daha fazla maç gerekli"}
        </span>
        {e.warnings.map((w) => (
          <span key={w} className="text-xs text-warn">
            {w}
          </span>
        ))}
        <span className="text-xs text-muted">Oranlar en eski {dateTime(oldest)} tarihli; oynamadan önce iddaa&apos;da kontrol et.</span>
        <button type="button" onClick={() => clearPicks()} className="ml-auto text-sm text-ink-2 underline-offset-4 hover:underline">
          Kuponu temizle
        </button>
      </div>
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div>
      <p className="kicker">{label}</p>
      <p className={`num text-lg font-semibold ${tone === "good" ? "text-good-ink" : tone === "bad" ? "text-critical-ink" : ""}`}>{value}</p>
    </div>
  );
}
