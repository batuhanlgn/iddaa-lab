import { pct, signedPct } from "@/lib/format";
import type { ScoutBacktest, ScoutBtSummary } from "@/lib/types";
import { SectionTitle, Stat } from "./ui";

const MARKET_LABEL: Record<string, string> = { ms: "Maç Sonucu", au: "2.5 Alt/Üst", cs: "Çifte Şans", kg: "KG", hnd: "Handikap" };

/** "2025-10-16T00:00:00Z" -> "16.10.2025" */
function day(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function tone(v: number | undefined): string {
  return v === undefined ? "" : v > 0 ? "text-good-ink" : v < 0 ? "text-critical-ink" : "";
}

function Row({ label, g, hint }: { label: string; g: ScoutBtSummary | undefined; hint?: string }) {
  if (!g || g.n === 0) {
    return (
      <tr className="border-b border-line/60 last:border-0">
        <td className="px-4 py-1.5 font-medium">{label}</td>
        <td colSpan={6} className="px-2 py-1.5 text-muted">
          seçim yok
        </td>
      </tr>
    );
  }
  return (
    <tr className="border-b border-line/60 last:border-0" title={hint}>
      <td className="px-4 py-1.5 font-medium">{label}</td>
      <td className="num px-2 py-1.5 text-right text-ink-2">{g.n.toLocaleString("tr-TR")}</td>
      <td className="num px-2 py-1.5 text-right">
        {pct(g.hit_rate, 1)} <span className="text-muted">/ {pct(g.p_market, 1)}</span>
      </td>
      <td className={`num px-2 py-1.5 text-right ${tone(g.edge_vs_market)}`}>{signedPct(g.edge_vs_market ?? 0)}</td>
      <td className="num px-2 py-1.5 text-right">{g.avg_odd?.toFixed(2)}</td>
      <td className={`num px-2 py-1.5 text-right ${tone(g.roi_close)}`}>{signedPct(g.roi_close ?? 0)}</td>
      <td className={`num px-4 py-1.5 text-right ${tone(g.roi_iddaa)}`}>
        {signedPct(g.roi_iddaa ?? 0)}
        {g.roi_iddaa_ci95 && (
          <span className="block text-[0.65rem] text-muted">
            %95: {signedPct(g.roi_iddaa_ci95[0])} … {signedPct(g.roi_iddaa_ci95[1])}
          </span>
        )}
      </td>
    </tr>
  );
}

export default function ScoutBacktestSection({ bt }: { bt: ScoutBacktest }) {
  const a = bt.all;
  const s = a.scout;
  const oneri = bt.verdicts.oneri ?? 0;
  const pas = bt.verdicts.pas ?? 0;
  // Filtre değerli mi: scout'un seçtikleri, elediklerinden (pas dediği maçlardaki model önerileri) belirgin iyi mi?
  // Güven aralığı karşı tarafın değerini dışarıda bırakmıyorsa "fark yok" denir (gürültüyü başarı saymamak için).
  const pasRoi = a.model_on_pas.roi_iddaa;
  const ci = s.roi_iddaa_ci95;
  const filterVerdict =
    s.n === 0 || a.model_on_pas.n === 0 || pasRoi === undefined || !ci
      ? "–"
      : ci[0] > pasRoi
        ? "✓ evet"
        : ci[1] < pasRoi
          ? "✕ hayır, daha kötü"
          : "≈ belirgin fark yok";
  return (
    <section>
      <SectionTitle right={<span className="kicker">walk-forward · {day(bt.window[0])} – {day(bt.window[1])}</span>}>
        Scout backtest
      </SectionTitle>
      <div className="panel rise flex flex-col gap-5 p-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Değerlendirilen maç" value={bt.n_matches.toLocaleString("tr-TR")} sub={`öneri ${oneri} · pas ${pas}`} />
          <Stat label="Scout isabeti" value={<span className="num">{pct(s.hit_rate, 1)}</span>} sub={`oranların ima ettiği ${pct(s.p_market, 1)}`} />
          <Stat
            label="Getiri (iddaa marjıyla)"
            value={<span className={`num ${tone(s.roi_iddaa)}`}>{signedPct(s.roi_iddaa ?? 0)}</span>}
            sub={`kapanış oranıyla ${signedPct(s.roi_close ?? 0)}`}
          />
          <Stat
            label="Filtre işe yarıyor mu?"
            value={filterVerdict}
            sub={`pas dediği maçlarda model önerisi: ${signedPct(a.model_on_pas.roi_iddaa ?? 0)}`}
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Grup</th>
                <th className="px-2 py-2 text-right font-medium">Seçim</th>
                <th className="px-2 py-2 text-right font-medium" title="Gerçekleşen isabet / kapanış oranının ima ettiği olasılık">
                  İsabet / piyasa
                </th>
                <th className="px-2 py-2 text-right font-medium" title="İsabet − piyasa olasılığı: pozitifse seçimler piyasadan iyi">
                  Fark
                </th>
                <th className="px-2 py-2 text-right font-medium">Ort. oran</th>
                <th className="px-2 py-2 text-right font-medium">Getiri (kapanış)</th>
                <th className="px-4 py-2 text-right font-medium">Getiri (iddaa)</th>
              </tr>
            </thead>
            <tbody>
              <Row label="Scout önerileri" g={a.scout} />
              <Row label="· güven yüksek" g={a.scout_yuksek} />
              <Row label="· güven orta" g={a.scout_orta} />
              {Object.entries(a.scout_by_market).map(([k, g]) => (
                <Row key={k} label={`· ${MARKET_LABEL[k] ?? k}`} g={g} />
              ))}
              <Row label="Model önerisi (tüm maçlar)" g={a.model_all} hint="Filtresiz model önerisi" />
              <Row label="Model önerisi · scout pas dedi" g={a.model_on_pas} hint="Scout'un elediği seçimler" />
              <Row label="İlk yarı · scout" g={bt.first_half.scout} />
              <Row label="İkinci yarı · scout" g={bt.second_half.scout} />
            </tbody>
          </table>
        </div>

        {Object.keys(bt.by_league).length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-ink-2">Lig bazında scout önerileri (en az 20 seçim)</summary>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <tbody>
                  {Object.entries(bt.by_league).map(([lg, g]) => (
                    <Row key={lg} label={bt.league_names[lg] ?? lg} g={g} />
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}

        <ul className="flex flex-col gap-1 text-[0.7rem] text-muted">
          {bt.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
          <li>
            • iddaa marjı (güncel bülten medyanı):{" "}
            {Object.entries(bt.iddaa_margins)
              .map(([k, v]) => `${k === "1:1:" ? "MS" : "2.5 A/Ü"} %${(v * 100).toFixed(1)}`)
              .join(" · ")}
          </li>
        </ul>
      </div>
    </section>
  );
}
