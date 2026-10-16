import { marketLine, odd, pct } from "@/lib/format";
import type {
  ScoutAxisSignal,
  ScoutItem,
  ScoutReportData,
  ScoutSection,
  ScoutSectionKey,
  ScoutSide,
  ScoutVerdict,
} from "@/lib/scout-types";
import { EvTag, SectionTitle } from "../ui";

/** Taraf etiketi: renk noktası + ikon + metin (renk tek başına anlam taşımaz). */
function sideStyle(side: ScoutSide, scout: ScoutReportData, section: ScoutSectionKey): { label: string; icon: string; dot: string; cls: string } {
  switch (side) {
    case "home":
      return { label: scout.home.name, icon: "⌂", dot: "var(--home)", cls: "border-home/50 text-ink" };
    case "away":
      return { label: scout.away.name, icon: "✈", dot: "var(--away)", cls: "border-away/50 text-ink" };
    case "draw":
      return { label: "Beraberlik", icon: "=", dot: "var(--draw)", cls: "border-line-strong text-ink-2" };
    case "goals_over":
      return { label: "Bol gol", icon: "▲", dot: "var(--accent)", cls: "border-accent/40 text-ink" };
    case "goals_under":
      return { label: "Az gol", icon: "▼", dot: "var(--muted)", cls: "border-line-strong text-ink-2" };
    case "neutral":
      return section === "risk"
        ? { label: "Risk", icon: "!", dot: "var(--warn)", cls: "border-warn/40 text-warn" }
        : { label: "Bilgi", icon: "·", dot: "var(--line-strong)", cls: "border-line text-muted" };
  }
}

function SideTag({ side, scout, section }: { side: ScoutSide; scout: ScoutReportData; section: ScoutSectionKey }) {
  const s = sideStyle(side, scout, section);
  return (
    <span className={`inline-flex max-w-[11rem] items-center gap-1 rounded border px-1.5 py-0.5 text-[0.65rem] font-medium ${s.cls}`}>
      <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: s.dot }} aria-hidden />
      <span aria-hidden>{s.icon}</span>
      <span className="truncate">{s.label}</span>
    </span>
  );
}

function WeightPips({ weight, risk }: { weight: number; risk: boolean }) {
  if (weight <= 0) return null;
  const n = weight >= 0.67 ? 3 : weight >= 0.34 ? 2 : 1;
  const word = n === 3 ? "güçlü" : n === 2 ? "orta" : "zayıf";
  const label = risk ? `Risk önemi: ${word}` : `Kanıt ağırlığı: ${word}`;
  return (
    <span className="num shrink-0 text-[0.55rem] tracking-[-0.1em] text-muted" title={`${label} (${weight.toFixed(2)})`} aria-label={label}>
      {"●".repeat(n)}
      {"○".repeat(3 - n)}
    </span>
  );
}

function CheckIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden className="shrink-0 text-good-ink">
      <circle cx="11" cy="11" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M6.5 11.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden className="shrink-0 text-ink-2">
      <circle cx="11" cy="11" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <line x1="8.5" y1="7" x2="8.5" y2="15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="13.5" y1="7" x2="13.5" y2="15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function VerdictCard({ verdict }: { verdict: ScoutVerdict }) {
  if (verdict.verdict === "pas") {
    return (
      <div className="rounded-xl border border-line-strong bg-surface-2 p-4" role="status">
        <div className="flex items-start gap-3">
          <PauseIcon />
          <div className="min-w-0">
            <p className="kicker">Scout hükmü · öneri yok</p>
            <p className="font-display text-2xl font-extrabold uppercase leading-tight">{verdict.headline}</p>
            <p className="mt-2 text-sm leading-relaxed text-ink-2">{verdict.reason}</p>
          </div>
        </div>
      </div>
    );
  }
  const pk = verdict.pick;
  const high = verdict.confidence === "yüksek";
  return (
    <div className="rounded-xl border border-good/40 bg-surface-2 p-4" role="status">
      <div className="flex items-start gap-3">
        <CheckIcon />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="kicker">Scout hükmü · öneri</p>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.7rem] font-medium ${high ? "border-good/40 text-good-ink" : "border-warn/40 text-warn"}`}
            >
              <span className="num text-[0.55rem] tracking-[-0.1em]" aria-hidden>
                {high ? "●●●" : "●●○"}
              </span>
              Güven: {verdict.confidence}
            </span>
          </div>
          <p className="font-display text-2xl font-extrabold uppercase leading-tight">{verdict.headline}</p>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
            <div className="col-span-2 min-w-0">
              <dt className="kicker">Pazar</dt>
              <dd className="truncate">{marketLine(pk.label, pk.line)}</dd>
            </div>
            <div>
              <dt className="kicker">Oran</dt>
              <dd className="num text-base font-semibold">{odd(pk.odd)}</dd>
            </div>
            <div>
              <dt className="kicker">Model / piyasa</dt>
              <dd className="num">
                {pct(pk.p_model)} / {pct(pk.p_market)}
              </dd>
            </div>
          </dl>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {pk.ev != null && <EvTag ev={pk.ev} validated={pk.family_validated} />}
            {!pk.family_validated && <span className="text-[0.7rem] text-muted">✕ Bu pazar ailesi backtest doğrulamasından geçmedi</span>}
            {!pk.same_as_model_pick && <span className="text-[0.7rem] text-muted">↺ Modelin ham önerisinin temkinli/alternatif karşılığı</span>}
          </div>
          <p className="mt-3 text-sm leading-relaxed text-ink-2">{verdict.reason}</p>
        </div>
      </div>
    </div>
  );
}

function AxisRow({ title, axis, scout, titles }: { title: string; axis: ScoutAxisSignal; scout: ScoutReportData; titles: Map<ScoutSectionKey, string> }) {
  if (axis.direction == null || Object.keys(axis.nets).length === 0) return null;
  const neutralKeys = (Object.keys(axis.nets) as ScoutSectionKey[]).filter(
    (k) => !axis.agree.some((a) => a === k) && !axis.disagree.some((d) => d === k),
  );
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-baseline sm:gap-3">
      <div className="flex shrink-0 items-center gap-2 sm:w-48">
        <span className="kicker">{title}</span>
        <SideTag side={axis.direction} scout={scout} section="guc" />
      </div>
      <ul className="flex flex-wrap gap-1.5 text-xs">
        {axis.agree.map((k) => (
          <li key={k} className="rounded border border-good/40 px-2 py-0.5 text-good-ink">
            ✓ {titles.get(k) ?? k}
          </li>
        ))}
        {axis.disagree.map((k) => (
          <li key={k} className="rounded border border-critical/40 px-2 py-0.5 text-critical-ink">
            ✕ {titles.get(k) ?? k}
          </li>
        ))}
        {neutralKeys.map((k) => (
          <li key={k} className="rounded border border-line px-2 py-0.5 text-muted">
            ■ {titles.get(k) ?? k}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ItemRow({ item, scout, section }: { item: ScoutItem; scout: ScoutReportData; section: ScoutSectionKey }) {
  return (
    <li className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-3">
      <span className="flex shrink-0 items-center gap-2 sm:w-40 sm:pt-0.5">
        <SideTag side={item.side} scout={scout} section={section} />
        <WeightPips weight={item.weight} risk={section === "risk"} />
      </span>
      <span className="min-w-0 text-sm leading-relaxed">{item.text}</span>
    </li>
  );
}

function SectionBlock({ section, scout }: { section: ScoutSection; scout: ScoutReportData }) {
  const wide = section.key === "risk" || section.key === "guc";
  return (
    <div className={`flex flex-col gap-3 rounded-lg bg-surface-2 p-4 ${wide ? "md:col-span-2" : ""}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-base font-extrabold uppercase tracking-wide">{section.title}</h3>
        {!section.available && <span className="kicker">veri yok</span>}
      </div>
      {section.note && <p className="text-sm text-muted">{section.note}</p>}
      {section.items.length > 0 && (
        <ul className="flex flex-col gap-2.5">
          {section.items.map((it, i) => (
            <ItemRow key={`${section.key}-${i}`} item={it} scout={scout} section={section.key} />
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ScoutReport({ scout }: { scout: ScoutReportData }) {
  const titles = new Map<ScoutSectionKey, string>(scout.sections.map((s) => [s.key, s.title.toLowerCase()]));
  return (
    <section className="panel rise flex flex-col gap-5 p-5" aria-label="Scout raporu">
      <SectionTitle right={<span className="kicker">{scout.version}</span>}>Scout raporu</SectionTitle>
      <p className="text-sm leading-relaxed text-ink-2">{scout.summary}</p>
      <VerdictCard verdict={scout.verdict} />
      <div className="flex flex-col gap-2">
        <p className="kicker">Kanıt uyumu</p>
        <AxisRow title="Sonuç" axis={scout.signals.result} scout={scout} titles={titles} />
        <AxisRow title="Gol" axis={scout.signals.goals} scout={scout} titles={titles} />
        <p className="text-[0.7rem] text-muted">✓ aynı yönde · ✕ karşı yönde · ■ nötr. Öneri için en az bir bağımsız bölümün (form, lig konumu, karşılıklı geçmiş) desteği gerekir.</p>
      </div>
      <div className="chalk-rule" />
      <div className="grid gap-4 md:grid-cols-2">
        {scout.sections.map((s) => (
          <SectionBlock key={s.key} section={s} scout={scout} />
        ))}
      </div>
      <p className="text-[0.7rem] text-muted">
        Ağırlık: ●●● güçlü · ●●○ orta · ●○○ zayıf kanıt. Toplam risk puanı <span className="num">{scout.risk_total.toFixed(2)}</span>.
      </p>
    </section>
  );
}
