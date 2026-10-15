import { dateTime } from "@/lib/format";
import type { MatchDetail } from "@/lib/types";
import { ConfidenceBadge, Crest } from "../ui";

export default function MatchHeader({ d }: { d: MatchDetail }) {
  const { match: m, model } = d;
  return (
    <header className="panel rise relative overflow-hidden px-5 py-6 sm:px-8">
      {/* Orta saha çizgisi ve santra yayı: yayın grafiği dokusu */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full text-line" aria-hidden preserveAspectRatio="none">
        <line x1="50%" y1="0" x2="50%" y2="100%" stroke="currentColor" strokeWidth="1" />
        <circle cx="50%" cy="50%" r="70" fill="none" stroke="currentColor" strokeWidth="1" />
      </svg>
      <div className="relative">
        <p className="kicker text-center">
          {m.country} · {m.league_name} · {dateTime(m.date_utc)}
          {m.venue ? ` · ${m.venue}` : ""}
          {m.neutral ? " · tarafsız saha" : ""}
        </p>
        <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3 sm:gap-8">
          <div className="flex min-w-0 flex-col items-end gap-2 text-right sm:flex-row sm:items-center sm:justify-end">
            <h1 className="font-display order-2 max-w-full break-words text-xl font-black uppercase leading-none sm:order-1 sm:text-5xl">{m.home.name}</h1>
            <span className="order-1 sm:order-2">
              <Crest team={m.home} size={56} />
            </span>
          </div>
          <div className="flex flex-col items-center">
            {model ? (
              <>
                <div className="num flex items-baseline gap-1 text-xl font-semibold sm:gap-2 sm:text-4xl">
                  <span style={{ color: "var(--ink)" }}>{model.lambda_home.toFixed(2)}</span>
                  <span className="text-muted">:</span>
                  <span>{model.lambda_away.toFixed(2)}</span>
                </div>
                <span className="kicker mt-1">beklenen gol</span>
              </>
            ) : (
              <span className="font-display text-3xl font-black text-muted">VS</span>
            )}
          </div>
          <div className="flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:items-center">
            <Crest team={m.away} size={56} />
            <h1 className="font-display max-w-full break-words text-xl font-black uppercase leading-none sm:text-5xl">{m.away.name}</h1>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2 text-xs">
          {model && <ConfidenceBadge level={model.confidence} notes={model.confidence_notes} />}
          <span className="rounded-full border border-line px-2 py-0.5 text-ink-2">
            Kadro: {m.lineup_confirmed ? "resmi kadro açıklandı" : "geçmiş maçlardan tahmini"}
          </span>
          {d.iddaa && <span className="rounded-full border border-line px-2 py-0.5 text-ink-2">iddaa MBS {d.iddaa.mbs ?? "–"}</span>}
          {model?.lineup_adj && model.lineup_adj.beta > 0 && (["home", "away"] as const).map((side) => {
            const f = model.lineup_adj![side];
            if (Math.abs(f - 1) < 0.005) return null;
            return (
              <span key={side} className={`rounded-full border px-2 py-0.5 ${f < 1 ? "border-critical/40 text-critical-ink" : "border-good/40 text-good-ink"}`}
                title="Resmi ilk 11'in hücum gücü, takımın olağan kadrosuna göre">
                Kadro etkisi · {m[side].short_name ?? m[side].name}: gol beklentisi {f > 1 ? "+" : ""}{((f - 1) * 100).toFixed(0)}%
              </span>
            );
          })}
          {model?.confidence_notes.map((n) => (
            <span key={n} className="rounded-full border border-warn/30 px-2 py-0.5 text-warn">
              {n}
            </span>
          ))}
        </div>
      </div>
    </header>
  );
}
