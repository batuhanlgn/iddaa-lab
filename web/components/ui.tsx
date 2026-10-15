import type { ReactNode } from "react";
import { pct, signedPct } from "@/lib/format";
import type { Confidence, Team } from "@/lib/types";

export function Crest({ team, size = 28 }: { team: Pick<Team, "name" | "logo">; size?: number }) {
  if (!team.logo) {
    return (
      <span
        className="grid shrink-0 place-items-center rounded-full bg-surface-3 font-display text-[0.7rem] font-extrabold uppercase text-ink-2"
        style={{ width: size, height: size }}
        aria-hidden
      >
        {team.name.slice(0, 2)}
      </span>
    );
  }
  return (
    // ESPN logo CDN'i; next/image optimizasyonu gereksiz (küçük PNG'ler)
    // eslint-disable-next-line @next/next/no-img-element
    <img src={team.logo} alt="" width={size} height={size} loading="lazy" referrerPolicy="no-referrer" className="shrink-0 object-contain" style={{ width: size, height: size }} />
  );
}

const CONF_STYLE: Record<Confidence, { cls: string; label: string; icon: string }> = {
  yüksek: { cls: "border-good/40 text-good-ink", label: "Güven: yüksek", icon: "●●●" },
  orta: { cls: "border-warn/40 text-warn", label: "Güven: orta", icon: "●●○" },
  düşük: { cls: "border-critical/40 text-critical-ink", label: "Güven: düşük", icon: "●○○" },
  yok: { cls: "border-line text-muted", label: "Model yok", icon: "○○○" },
};

export function ConfidenceBadge({ level, notes }: { level: Confidence; notes?: string[] }) {
  const s = CONF_STYLE[level];
  return (
    <span
      title={notes && notes.length ? notes.join(" · ") : s.label}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.7rem] font-medium ${s.cls}`}
    >
      <span className="num text-[0.55rem] tracking-[-0.1em]" aria-hidden>
        {s.icon}
      </span>
      {s.label}
    </span>
  );
}

/** Beklenen değer etiketi: renk + ikon + metin (renk tek başına anlam taşımaz). */
export function EvTag({ ev, validated = true }: { ev: number; validated?: boolean }) {
  const good = ev >= 0.04;
  const neutral = ev > -0.04 && ev < 0.04;
  const cls = good ? "border-good/40 text-good-ink" : neutral ? "border-line text-ink-2" : "border-critical/30 text-critical-ink";
  const icon = good ? "▲" : neutral ? "■" : "▼";
  return (
    <span
      className={`num inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.7rem] ${cls} ${validated ? "" : "opacity-60"}`}
      title={validated ? "Beklenen değer (model+piyasa harmanı)" : "Bu pazar ailesi backtest doğrulamasından geçmedi"}
    >
      <span aria-hidden>{icon}</span>
      EV {signedPct(ev)}
    </span>
  );
}

/** 1X2 olasılık çubuğu: ev/beraberlik/deplasman, 2px yüzey boşluğu, etiketler metin renginde. */
export function ProbBar({ ms, height = 8, showLabels = true }: { ms: Record<string, number>; height?: number; showLabels?: boolean }) {
  const parts: { k: string; p: number; color: string; label: string }[] = [
    { k: "1", p: ms["1"] ?? 0, color: "var(--home)", label: "1" },
    { k: "0", p: ms["0"] ?? 0, color: "var(--draw)", label: "X" },
    { k: "2", p: ms["2"] ?? 0, color: "var(--away)", label: "2" },
  ];
  return (
    <div className="w-full">
      <div className="flex w-full gap-[2px] overflow-hidden rounded-[4px]" style={{ height }} role="img" aria-label={`Ev ${pct(parts[0].p)}, beraberlik ${pct(parts[1].p)}, deplasman ${pct(parts[2].p)}`}>
        {parts.map((x) => (
          <div key={x.k} style={{ width: `${x.p * 100}%`, background: x.color }} />
        ))}
      </div>
      {showLabels && (
        <div className="num mt-1 flex justify-between text-[0.72rem] text-ink-2">
          {parts.map((x) => (
            <span key={x.k} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-[2px]" style={{ background: x.color }} aria-hidden />
              {x.label} {pct(x.p)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function PageHeader({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <div className="rise mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="kicker mb-1">{kicker}</p>
        <h1 className="font-display text-4xl font-black uppercase leading-[0.95] sm:text-5xl">{title}</h1>
      </div>
      {children}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="font-display text-xl font-extrabold uppercase tracking-wide">{children}</h2>
      {right}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
      <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden className="text-line-strong">
        <rect x="2" y="2" width="40" height="40" rx="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <line x1="22" y1="2" x2="22" y2="42" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="22" cy="22" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <p className="font-display text-xl font-extrabold uppercase">{title}</p>
      {children && <div className="max-w-xl text-sm text-ink-2">{children}</div>}
      {action}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="kicker">{label}</p>
      <p className="mt-1 text-2xl font-semibold leading-tight">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export function SkeletonRows({ n = 6, h = 64 }: { n?: number; h?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label="Yükleniyor">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skeleton w-full" style={{ height: h }} />
      ))}
    </div>
  );
}
