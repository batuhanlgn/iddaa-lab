"use client";

import { useState } from "react";
import type { CalibrationBin } from "@/lib/types";

/** Güvenilirlik diyagramı: x = tahmin, y = gerçekleşen; köşegen = mükemmel kalibrasyon. Nokta alanı ~ örnek sayısı. */
export default function Calibration({ bins, label, color = "var(--home)" }: { bins: CalibrationBin[]; label: string; color?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const S = 220;
  const pad = 28;
  const inner = S - pad - 8;
  const sx = (v: number) => pad + v * inner;
  const sy = (v: number) => 8 + inner - v * inner;
  const maxN = Math.max(...bins.map((b) => b.n), 1);
  const r = (n: number) => 4 + 5 * Math.sqrt(n / maxN);
  const pts = bins.map((b) => `${sx(b.pred)},${sy(b.obs)}`).join(" ");
  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${S} ${S}`} className="w-full max-w-[280px]" role="img" aria-label={label}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={sx(0)} x2={sx(1)} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth="1" />
            <text x={pad - 4} y={sy(t) + 3} fontSize="8" textAnchor="end" fill="var(--muted)" className="num">
              {Math.round(t * 100)}
            </text>
            <text x={sx(t)} y={S - 8} fontSize="8" textAnchor="middle" fill="var(--muted)" className="num">
              {Math.round(t * 100)}
            </text>
          </g>
        ))}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--line-strong)" strokeWidth="1" />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" opacity="0.5" />
        {bins.map((b, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={sx(b.pred)} cy={sy(b.obs)} r={r(b.n) + 6} fill="transparent" />
            <circle cx={sx(b.pred)} cy={sy(b.obs)} r={r(b.n)} fill={color} stroke="var(--surface)" strokeWidth="2" opacity={hover == null || hover === i ? 1 : 0.5} />
          </g>
        ))}
      </svg>
      <figcaption className="mt-1 text-[0.68rem] text-muted">x: tahmin edilen % · y: gerçekleşen % · köşegen: ideal</figcaption>
      {hover != null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-line bg-surface-3 px-2 py-1 text-xs shadow-lg"
          style={{ left: `${(sx(bins[hover].pred) / S) * 100}%`, top: `${(sy(bins[hover].obs) / S) * 100}%` }}
        >
          Tahmin <b className="num">%{(bins[hover].pred * 100).toFixed(1)}</b> · gerçekleşen <b className="num">%{(bins[hover].obs * 100).toFixed(1)}</b> ·{" "}
          <span className="num">n={bins[hover].n.toLocaleString("tr-TR")}</span>
        </div>
      )}
    </figure>
  );
}
