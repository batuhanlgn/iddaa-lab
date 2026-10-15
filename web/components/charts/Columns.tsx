"use client";

import { useState } from "react";

export interface ColumnDatum {
  x: string;
  y: number;
  tip: string;
}

/** Tek seri sütun grafiği: ≤24px sütun, 4px yuvarlak veri ucu, kılcal taban çizgisi, sütun başına hover ipucu. */
export default function Columns({
  data,
  color,
  height = 150,
  label,
  highlight,
}: {
  data: ColumnDatum[];
  color: string;
  height?: number;
  label: string;
  highlight?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 360;
  const padL = 30;
  const padB = 20;
  const padT = 14;
  const innerW = W - padL - 6;
  const innerH = height - padB - padT;
  const max = Math.max(...data.map((d) => d.y), 1e-9);
  const niceMax = Math.ceil((max * 100) / 5) * 5 / 100 || max;
  const band = innerW / Math.max(data.length, 1);
  const bw = Math.min(24, band * 0.7);
  const ticks = [0, niceMax / 2, niceMax];
  const yOf = (v: number) => padT + innerH - (v / niceMax) * innerH;
  const peak = data.reduce((b, d, i) => (d.y > data[b].y ? i : b), 0);

  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - 6} y1={yOf(t)} y2={yOf(t)} stroke="var(--grid)" strokeWidth="1" />
            <text x={padL - 6} y={yOf(t) + 3} textAnchor="end" className="num" fontSize="9" fill="var(--muted)">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * band + (band - bw) / 2;
          const y = yOf(d.y);
          const h = Math.max(padT + innerH - y, 0);
          const r = Math.min(4, h);
          const active = hover === i || d.x === highlight;
          return (
            <g key={d.x}>
              {h > 0 && (
                <path
                  d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${y + h} Z`}
                  fill={color}
                  opacity={hover == null || active ? 1 : 0.55}
                />
              )}
              <text x={x + bw / 2} y={height - 6} textAnchor="middle" fontSize="9" fill="var(--muted)" className="num">
                {d.x}
              </text>
              {i === peak && hover == null && (
                <text x={x + bw / 2} y={y - 4} textAnchor="middle" fontSize="9.5" fill="var(--ink)" className="num">
                  {Math.round(d.y * 100)}%
                </text>
              )}
              {/* hit alanı sütundan büyük */}
              <rect
                x={padL + i * band}
                y={padT}
                width={band}
                height={innerH + padB}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            </g>
          );
        })}
        <line x1={padL} x2={W - 6} y1={padT + innerH} y2={padT + innerH} stroke="var(--line-strong)" strokeWidth="1" />
      </svg>
      {hover != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-md border border-line bg-surface-3 px-2 py-1 text-xs shadow-lg"
          style={{ left: `${((padL + hover * band + band / 2) / W) * 100}%` }}
        >
          {data[hover].tip}
        </div>
      )}
    </figure>
  );
}
