import { dateTime, pct } from "@/lib/format";
import type { MatchDetail } from "@/lib/types";
import { SectionTitle } from "../ui";

const FAM: Record<string, string> = { ms: "Maç sonucu", au: "Alt/Üst", kg: "Karşılıklı gol", iy: "İlk yarı", korner: "Korner" };

export default function ModelNotes({ d }: { d: MatchDetail }) {
  const m = d.model!;
  return (
    <section className="panel rise flex flex-col gap-4 p-5">
      <SectionTitle>Model notları</SectionTitle>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Model sürümü</dt>
        <dd className="num truncate">{d.model_version}</dd>
        <dt className="text-muted">Veri kesimi</dt>
        <dd className="num">{dateTime(m.as_of)}</dd>
        <dt className="text-muted">Zaman sönümü (ξ)</dt>
        <dd className="num">{m.params.xi} / gün (yarı ömür ≈ {Math.round(Math.log(2) / m.params.xi)} gün)</dd>
        <dt className="text-muted">Takım büzülmesi (σ)</dt>
        <dd className="num">{m.params.sigma}</dd>
        <dt className="text-muted">Dixon-Coles ρ</dt>
        <dd className="num">{m.rho.toFixed(3)}</dd>
        <dt className="text-muted">1. yarı gol payı</dt>
        <dd className="num">{pct(m.p1, 1)}</dd>
        <dt className="text-muted">Harman (model ağırlığı)</dt>
        <dd className="num">
          {pct(m.blend_weight)} {m.blend_calibrated ? "· arşivden kalibre" : "· varsayılan"}
        </dd>
      </dl>
      <div>
        <p className="kicker mb-2">Pazar ailesi doğrulaması (walk-forward backtest)</p>
        <ul className="flex flex-wrap gap-1.5 text-xs">
          {Object.entries(FAM).map(([k, label]) => {
            const ok = m.family_validation?.[k];
            return (
              <li key={k} className={`rounded border px-2 py-1 ${ok ? "border-good/40 text-good-ink" : "border-line text-muted"}`}>
                {ok ? "✓" : "✕"} {label}
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-[0.7rem] leading-relaxed text-muted">
          Doğrulanan aileler, değerlendirme döneminde lig taban oranlarından daha iyi log-loss ve düşük kalibrasyon hatası
          gösterenlerdir. Doğrulanmayanlar gösterilir ama otomatik kupona alınmaz.
        </p>
      </div>
    </section>
  );
}
