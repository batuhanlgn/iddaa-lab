"use client";

import { useState } from "react";
import { fairOdd, pct } from "@/lib/format";
import type { MatchDetail } from "@/lib/types";

// Sıralı tek ton (mavi) rampa: açık = düşük, koyu = yüksek (koyu temada tersine yakın ton adımları seçili)
const STEPS = ["var(--seq-0)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];

export default function ScoreHeatmap({ d }: { d: MatchDetail }) {
  const sm = d.score_matrix!;
  const max = Math.max(...sm.p.flat());
  const [hover, setHover] = useState<{ h: number; a: number } | null>(null);
  const step = (v: number) => STEPS[Math.min(STEPS.length - 1, Math.floor((v / max) * (STEPS.length - 1) + 0.5))];
  const ink = (v: number) => (v / max > 0.55 ? "var(--page)" : "var(--ink-2)");
  const hv = hover ? sm.p[hover.h][hover.a] : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto">
        <div className="grid min-w-[320px] gap-[2px]" style={{ gridTemplateColumns: `2rem repeat(${sm.size}, minmax(0,1fr))` }}>
          <span />
          {Array.from({ length: sm.size }, (_, a) => (
            <span key={a} className="num pb-1 text-center text-xs text-muted">
              {a}
            </span>
          ))}
          {sm.p.map((row, h) => (
            <Row key={h} h={h}>
              {row.map((v, a) => (
                <button
                  key={a}
                  type="button"
                  onMouseEnter={() => setHover({ h, a })}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover({ h, a })}
                  onBlur={() => setHover(null)}
                  aria-label={`${h}-${a}: ${pct(v, 1)}`}
                  className="num relative grid aspect-square place-items-center rounded-[3px] text-[0.68rem] transition-transform hover:z-10 hover:scale-110"
                  style={{
                    background: step(v),
                    color: ink(v),
                    outline: hover && hover.h === h && hover.a === a ? "2px solid var(--ink)" : undefined,
                  }}
                >
                  {v >= 0.04 ? `${(v * 100).toFixed(0)}` : ""}
                </button>
              ))}
            </Row>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="min-h-5 text-ink-2" aria-live="polite">
          {hover && hv != null ? (
            <>
              <b className="num text-ink">
                {d.match.home.name} {hover.h} – {hover.a} {d.match.away.name}
              </b>{" "}
              · {pct(hv, 1)} · adil oran {fairOdd(hv)}
            </>
          ) : (
            <>
              Hücre üzerine gel: skor olasılığı. Tablo dışı skorlar: <span className="num">{pct(sm.other, 1)}</span>
            </>
          )}
        </p>
        <div className="flex items-center gap-1 text-xs text-muted" aria-hidden>
          az
          {STEPS.slice(1).map((s) => (
            <span key={s} className="h-3 w-4 rounded-[2px]" style={{ background: s }} />
          ))}
          çok
        </div>
      </div>
      {d.top_scores && (
        <div>
          <p className="kicker mb-2">En olası skorlar</p>
          <div className="flex flex-wrap gap-1.5">
            {d.top_scores.slice(0, 6).map((s) => (
              <span key={`${s.home}-${s.away}`} className="num rounded-md border border-line bg-surface-2 px-2 py-1 text-sm">
                <b>
                  {s.home}-{s.away}
                </b>{" "}
                <span className="text-muted">{pct(s.p, 1)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ h, children }: { h: number; children: React.ReactNode }) {
  return (
    <>
      <span className="num grid place-items-center text-xs text-muted">{h}</span>
      {children}
    </>
  );
}
