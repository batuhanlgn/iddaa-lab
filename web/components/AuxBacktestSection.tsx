import { pct } from "@/lib/format";
import type { Backtest } from "@/lib/types";
import { SectionTitle } from "./ui";

const MARKET: Record<string, string> = {
  korner_au: "Toplam korner A/Ü",
  ev_korner_au: "Ev sahibi korner A/Ü",
  dep_korner_au: "Deplasman korner A/Ü",
  korner_kdc: "Kim daha çok korner",
  korner_ar: "Toplam korner aralığı",
  korner_hnd: "Korner handikabı (ev)",
  kart_au: "Toplam kart A/Ü",
  iy_kart_au: "İlk yarı kart A/Ü",
  kart_kdc: "Kim daha çok kart",
  kirmizi: "Kırmızı kart olur mu",
};

function label(sub: string): string {
  const [key, line] = sub.split(" ");
  return line ? `${MARKET[key] ?? key} ${line}` : (MARKET[key] ?? key);
}

/** Korner ve kart aileleri: pazar türü ve çizgi bazında değerlendirme dilimi sonuçları (backtest.aux_validation). */
export default function AuxBacktestSection({ bt }: { bt: Backtest }) {
  const fams = (["korner", "kart"] as const).filter((f) => bt.summary[f]?.lines);
  if (fams.length === 0) return null;
  return (
    <section>
      <SectionTitle right={<span className="kicker">değerlendirme dilimi · lig taban oranına karşı</span>}>Korner ve kart: pazar ve çizgi bazında</SectionTitle>
      <div className="grid gap-4 lg:grid-cols-2">
        {fams.map((f) => {
          const s = bt.summary[f];
          const fv = bt.family_validation[f];
          const chosen = bt.aux_tuning?.[f]?.chosen;
          const lines = Object.entries(s.lines ?? {});
          return (
            <div key={f} className="panel overflow-x-auto">
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-2">
                <p className="text-sm font-semibold">{f === "korner" ? "Korner" : "Kart (iddaa sayımı)"}</p>
                <p className={`text-xs ${fv?.validated ? "text-good-ink" : "text-warn"}`}>
                  {fv?.validated ? "✓ aile doğrulandı" : "✕ aile doğrulanmadı: kupon deneysel"}
                </p>
              </div>
              <table className="w-full min-w-[520px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-1.5 font-medium">Pazar / çizgi</th>
                    <th className="px-2 py-1.5 text-right font-medium">n</th>
                    <th className="px-2 py-1.5 text-right font-medium">Model</th>
                    <th className="px-2 py-1.5 text-right font-medium">Taban</th>
                    <th className="px-2 py-1.5 text-right font-medium">Kazanç</th>
                    <th className="px-2 py-1.5 text-right font-medium">ECE</th>
                    <th className="px-4 py-1.5 font-medium">Kupona açık</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/60">
                  {lines.map(([sub, r]) => {
                    const ok = fv?.lines?.[sub]?.validated ?? r.validated;
                    return (
                      <tr key={sub}>
                        <td className="px-4 py-1.5">{label(sub)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{r.n.toLocaleString("tr-TR")}</td>
                        <td className="num px-2 py-1.5 text-right">{r.model_logloss.toFixed(4)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{r.base_logloss.toFixed(4)}</td>
                        <td className={`num px-2 py-1.5 text-right font-semibold ${r.gain > 0 ? "text-good-ink" : "text-critical-ink"}`}>
                          {r.gain > 0 ? "+" : ""}
                          {r.gain.toFixed(4)}
                        </td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{pct(r.ece, 1)}</td>
                        <td className="px-4 py-1.5">{ok ? <span className="text-good-ink">✓</span> : <span className="text-muted">✕</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {chosen && (
                <p className="num px-4 py-2 text-[0.7rem] text-muted">
                  Seçilen ayar: ξ {chosen.xi} · σ {chosen.sigma} · toplam NB k {chosen.k_total} · pay φ {chosen.phi?.toFixed(1)} · lig
                  ortalamasına büzülme β {chosen.beta ?? 1}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        Taban: ligin son 400 gündeki oranı (az maçlı liglerde genel orana büzülmüş). Pazar türü kupona açılır: n ≥ 300, kazanç
        &gt; 0,002 ve kalibrasyon hatası &lt; %3; ayrıca o çizgide kazanç &gt; 0 olmalı. Geçmiş korner/kart oranı olmadığından
        kâr backtest&apos;i yapılamıyor; doğrulama olasılık kalitesidir, kuponlar canlıda izlenir.
      </p>
    </section>
  );
}
