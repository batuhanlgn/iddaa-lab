import { Suspense } from "react";
import Calibration from "@/components/charts/Calibration";
import ErrorPanel from "@/components/ErrorPanel";
import { EmptyState, PageHeader, SectionTitle, SkeletonRows, Stat } from "@/components/ui";
import { dateTime, pct, signedPct } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { PerformanceResponse } from "@/lib/types";

const FAM: Record<string, string> = {
  ms: "Maç sonucu (1X2)",
  au: "Alt/Üst 2.5",
  kg: "Karşılıklı gol",
  iy: "İlk yarı sonucu",
  iyms: "İY/MS",
  korner: "Korner 9.5 (deneysel)",
};
const PLAYER: Record<string, string> = {
  p_sot_1: "Oyuncu 1+ isabetli şut",
  p_shots_1: "Oyuncu 1+ şut",
  p_goal: "Oyuncu gol",
  p_play: "Oyuncu oynar mı",
  team_sot_4plus: "Takım 4+ isabetli şut",
};

async function Perf() {
  let d: PerformanceResponse;
  try {
    d = await getJSON<PerformanceResponse>("/api/performance");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Performans verisi alınamadı."} />;
  }
  const bt = d.backtest;
  if (!bt) {
    return (
      <EmptyState title="Backtest henüz çalışmadı">
        Walk-forward doğrulama ilk kurulumda veri indirildikten sonra otomatik çalışır. Veri sayfasından durumu izleyebilir ya
        da manuel başlatabilirsin.
      </EmptyState>
    );
  }
  const fams = Object.entries(bt.summary).filter(([k]) => k in FAM);
  const ms = bt.summary.ms;
  return (
    <div className="flex flex-col gap-10">
      <section className="panel rise grid gap-6 p-5 sm:grid-cols-4">
        <Stat
          label="MS log-loss kazancı"
          value={ms ? <span className={ms.base_logloss - ms.model_logloss > 0 ? "text-good-ink" : "text-critical-ink"}>{(ms.base_logloss - ms.model_logloss).toFixed(4)}</span> : "–"}
          sub="lig taban oranına göre (yüksek = iyi)"
        />
        <Stat label="Değerlendirilen maç" value={ms ? ms.n.toLocaleString("tr-TR") : "–"} sub={`${dateTime(bt.eval_window[0])} – ${dateTime(bt.eval_window[1])}`} />
        <Stat label="Seçilen ξ / σ" value={<span className="num">{bt.params.xi} / {bt.params.sigma}</span>} sub="ayarlama diliminde seçildi" />
        <Stat
          label="Model-piyasa harmanı"
          value={
            !d.blend_calibration
              ? "–"
              : d.blend_calibration.status === "kalibre"
                ? `✓ w = ${d.blend_calibration.weight}`
                : d.blend_calibration.status === "dogrulanamadi"
                  ? "✕ piyasa daha iyi"
                  : `${d.blend_calibration.n}/${d.blend_calibration.required}`
          }
          sub={
            d.blend_calibration?.holdout_blend_logloss != null
              ? `ayrı dilim log-loss: harman ${d.blend_calibration.holdout_blend_logloss.toFixed(4)} · piyasa ${d.blend_calibration.holdout_market_logloss?.toFixed(4)} · model ${d.blend_calibration.holdout_model_logloss?.toFixed(4)}`
              : "sonuçlanmış, tahmini arşivli iddaa maçı (yetince değer kuponları açılır)"
          }
        />
      </section>

      <section>
        <SectionTitle right={<span className="kicker">değerlendirme dilimi · sızıntısız haftalık yeniden eğitim</span>}>Pazar aileleri</SectionTitle>
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Pazar</th>
                <th className="px-2 py-2 text-right font-medium">n</th>
                <th className="px-2 py-2 text-right font-medium">Model log-loss</th>
                <th className="px-2 py-2 text-right font-medium">Taban oran</th>
                <th className="px-2 py-2 text-right font-medium">Basit Poisson</th>
                <th className="px-2 py-2 text-right font-medium">Brier (model / taban)</th>
                <th className="px-2 py-2 text-right font-medium">Kalibrasyon hatası</th>
                <th className="px-4 py-2 font-medium">Kupona açık</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {fams.map(([k, f]) => {
                const famKey = k === "iyms" ? "iy" : k;
                const v = bt.family_validation[famKey];
                const better = f.model_logloss < f.base_logloss;
                return (
                  <tr key={k}>
                    <td className="px-4 py-2 font-medium">{FAM[k]}</td>
                    <td className="num px-2 py-2 text-right text-ink-2">{f.n.toLocaleString("tr-TR")}</td>
                    <td className={`num px-2 py-2 text-right font-semibold ${better ? "text-good-ink" : "text-critical-ink"}`}>
                      {better ? "▲" : "▼"} {f.model_logloss.toFixed(4)}
                    </td>
                    <td className="num px-2 py-2 text-right text-ink-2">{f.base_logloss.toFixed(4)}</td>
                    <td className="num px-2 py-2 text-right text-ink-2">{f.simple_logloss != null ? f.simple_logloss.toFixed(4) : "–"}</td>
                    <td className="num px-2 py-2 text-right text-ink-2">
                      {f.model_brier.toFixed(4)} / {f.base_brier.toFixed(4)}
                    </td>
                    <td className="num px-2 py-2 text-right text-ink-2">{f.ece != null ? pct(f.ece, 1) : "–"}</td>
                    <td className="px-4 py-2">
                      {k === "iyms" ? (
                        <span className="text-xs text-muted">İY ailesine dahil</span>
                      ) : v?.validated ? (
                        <span className="text-good-ink">✓ evet</span>
                      ) : (
                        <span className="text-muted">✕ hayır</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted">
          Log-loss düşük olan iyidir. Taban oran: ligin son 400 gündeki sonuç frekansları (as-of). Basit Poisson: hiyerarşi ve
          Dixon-Coles düzeltmesi olmayan takım modeli. Kupona açılma koşulu: n ≥ 300, tabandan anlamlı iyi log-loss ve kalibrasyon
          hatası &lt; %3.
        </p>
      </section>

      <section>
        <SectionTitle right={<span className="kicker">tüm sonuçlar · nokta büyüklüğü = örnek</span>}>Kalibrasyon</SectionTitle>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {fams.map(([k, f]) => (
            <div key={k} className="panel p-4">
              <p className="mb-2 text-sm font-semibold">{FAM[k]}</p>
              <Calibration bins={f.calibration} label={`${FAM[k]} kalibrasyon grafiği`} />
            </div>
          ))}
        </div>
      </section>

      {d.player_backtest && (
        <section>
          <SectionTitle right={<span className="kicker">{d.player_backtest.metrics.p_sot_1?.n.toLocaleString("tr-TR") ?? 0} oyuncu-maç</span>}>Oyuncu simülasyonu doğrulaması</SectionTitle>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(d.player_backtest.metrics).map(([k, m]) => (
              <div key={k} className="panel p-4">
                <p className="text-sm font-semibold">{PLAYER[k] ?? k}</p>
                <p className="num mb-2 text-xs text-ink-2">
                  log-loss {m.model_logloss.toFixed(4)} (taban {m.base_logloss.toFixed(4)}) · ort. tahmin {pct(m.mean_pred, 1)} / gerçek {pct(m.mean_obs, 1)}
                </p>
                <Calibration bins={m.calibration} label={`${PLAYER[k] ?? k} kalibrasyon`} color="var(--away)" />
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">
            Taban: değerlendirme dilimindeki genel oran (iyimser bir taban; model bunu yenebiliyorsa oyuncuya özgü bilgi
            taşıyor demektir).
          </p>
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <SectionTitle>Hiperparametre ayarı</SectionTitle>
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">ξ</th>
                  <th className="px-2 py-2 font-medium">σ</th>
                  <th className="px-4 py-2 text-right font-medium">MS log-loss (ayarlama)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {[...bt.tuning].sort((a, b) => a.ms_logloss - b.ms_logloss).map((t) => {
                  const chosen = t.xi === bt.params.xi && t.sigma === bt.params.sigma;
                  return (
                    <tr key={`${t.xi}-${t.sigma}`} className={chosen ? "bg-accent/10" : ""}>
                      <td className="num px-4 py-1.5">{t.xi}</td>
                      <td className="num px-2 py-1.5">{t.sigma}</td>
                      <td className="num px-4 py-1.5 text-right">
                        {t.ms_logloss.toFixed(4)} {chosen && <span className="text-xs text-good-ink">✓ seçildi</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <SectionTitle>Lig bazında MS</SectionTitle>
          <div className="panel max-h-[420px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Lig</th>
                  <th className="px-2 py-2 text-right font-medium">n</th>
                  <th className="px-4 py-2 text-right font-medium">Kazanç</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {Object.entries(bt.by_league)
                  .sort((a, b) => b[1].base_logloss - b[1].model_logloss - (a[1].base_logloss - a[1].model_logloss))
                  .map(([lg, v]) => {
                    const gain = v.base_logloss - v.model_logloss;
                    return (
                      <tr key={lg}>
                        <td className="px-4 py-1.5">{d.league_names[lg] ?? lg}</td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{v.n}</td>
                        <td className={`num px-4 py-1.5 text-right ${gain >= 0 ? "text-good-ink" : "text-critical-ink"}`}>
                          {gain >= 0 ? "▲" : "▼"} {gain.toFixed(4)}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <SectionTitle>Kupon arşivi (ileriye dönük)</SectionTitle>
        {Object.keys(d.coupons).length === 0 ? (
          <EmptyState title="Henüz sonuçlanmış kupon yok">Model kuponları arşivlendikçe ve maçlar bittikçe burada gerçek isabet ve ROI görünür.</EmptyState>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(d.coupons).map(([k, s]) => (
              <div key={k} className="panel p-4">
                <Stat
                  label={({ deger: "Değer", olasilik: "Yüksek olasılık", dengeli: "Dengeli", oyuncu: "Oyuncu" } as Record<string, string>)[k] ?? k}
                  value={`${s.won}/${s.settled}`}
                  sub={`beklenen ${s.expected_hits.toFixed(1)} · ROI ${s.roi == null ? "–" : signedPct(s.roi)}`}
                />
              </div>
            ))}
          </div>
        )}
      </section>
      <p className="text-xs text-muted">Backtest zamanı: {dateTime(bt.created_at)}</p>
    </div>
  );
}

export default function PerformancePage() {
  return (
    <>
      <PageHeader kicker="Walk-forward backtest · sızıntısız" title="Model performansı" />
      <Suspense fallback={<SkeletonRows n={5} h={120} />}>
        <Perf />
      </Suspense>
    </>
  );
}
