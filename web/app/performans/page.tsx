import { Suspense } from "react";
import Calibration from "@/components/charts/Calibration";
import ErrorPanel from "@/components/ErrorPanel";
import ScoutBacktestSection from "@/components/ScoutBacktestSection";
import { EmptyState, PageHeader, SectionTitle, SkeletonRows, Stat } from "@/components/ui";
import { dateTime, marketLine, odd, pct, signedPct } from "@/lib/format";
import { KIND } from "@/components/coupons/CouponHistory";
import type { Backtest, TrackingGroup } from "@/lib/types";
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
  p_sot_2: "Oyuncu 2+ isabetli şut",
  p_shots_1: "Oyuncu 1+ şut",
  p_shots_2: "Oyuncu 2+ şut",
  p_shots_3: "Oyuncu 3+ şut",
  p_goal: "Oyuncu gol",
  p_play: "Oyuncu oynar mı",
  team_sot: "Takım 3+/4+/5+ isabetli şut",
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
        <Stat
          label="Seçilen ξ / σ / α"
          value={<span className="num">{bt.params.xi} / {bt.params.sigma} / {bt.params.alpha ?? 1}</span>}
          sub={`α: takım gücünde gol ağırlığı (${bt.params.alpha != null && bt.params.alpha < 1 ? `isabetli şut payı %${Math.round((1 - bt.params.alpha) * 100)}` : "yalnız gol"}) · kalibrasyon ${bt.score_calibration?.used ? `açık (t=${bt.score_calibration.t.toFixed(2)}, g=${bt.score_calibration.g.toFixed(2)})` : "kapalı"}`}
        />
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

      {d.scout_backtest && <ScoutBacktestSection bt={d.scout_backtest} />}
      {d.tracking && <TrackingSection t={d.tracking} />}
      {d.live_picks && <LivePicksSection s={d.live_picks} />}

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
                  {m.calibrated ? " · ✓ kalibrasyon uygulanıyor" : ""}
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
          {bt.xg_tuning && <XgTuning x={bt.xg_tuning} />}
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
                  label={KIND[k] ?? k}
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

function XgTuning({ x }: { x: NonNullable<Backtest["xg_tuning"]> }) {
  const b = x.val_bootstrap;
  return (
    <div className="panel mt-3 p-4 text-sm">
      <p className="kicker mb-1">xG ağırlığı (Understat)</p>
      <p className={x.accepted ? "text-good-ink" : "text-ink-2"}>
        {x.accepted ? `✓ Devrede: w = ${x.xg_weight}` : "■ Kullanılmıyor"}
        {x.tune_best !== undefined && !x.accepted && <span className="text-muted"> · ayarlamada en iyi w = {x.tune_best}</span>}
      </p>
      {b ? (
        <p className="num mt-1 text-xs text-ink-2">
          Doğrulama (MS + A/Ü + KG): log-loss {x.val_ll_without?.toFixed(4)} → {x.val_ll_with?.toFixed(4)} · maç başı kazanç{" "}
          {b.mean_gain >= 0 ? "+" : ""}
          {b.mean_gain.toFixed(4)} (%90: {b.ci90[0].toFixed(4)} … {b.ci90[1].toFixed(4)}) · daha iyi olma olasılığı %
          {Math.round(b.p_better * 100)} (eşik %95)
        </p>
      ) : (
        x.note && <p className="mt-1 text-xs text-muted">{x.note}</p>
      )}
      <p className="mt-1 text-[0.7rem] text-muted">Ayarlama dilimindeki xG&apos;li maç: {x.n_tune_xg_matches.toLocaleString("tr-TR")}</p>
    </div>
  );
}

function TrackRow({ label, g }: { label: string; g: TrackingGroup }) {
  const good = (v: number | null) => (v == null ? "" : v > 0 ? "text-good-ink" : v < 0 ? "text-critical-ink" : "");
  return (
    <tr>
      <td className="px-4 py-1.5 font-medium">{label}</td>
      <td className="num px-2 py-1.5 text-right text-ink-2">{g.n}</td>
      <td className={`num px-2 py-1.5 text-right ${good(g.clv_mean)}`}>{g.clv_mean == null ? "–" : signedPct(g.clv_mean)}</td>
      <td className="num px-2 py-1.5 text-right">{g.beat_close_pct == null ? "–" : pct(g.beat_close_pct)}</td>
      <td className="num px-2 py-1.5 text-right text-ink-2">{g.settled}</td>
      <td className="num px-2 py-1.5 text-right">
        {g.hit_rate == null ? "–" : pct(g.hit_rate)} <span className="text-muted">/ {g.expected_hit_rate == null ? "–" : pct(g.expected_hit_rate)}</span>
      </td>
      <td className={`num px-4 py-1.5 text-right ${good(g.roi)}`}>{g.roi == null ? "–" : signedPct(g.roi)}</td>
    </tr>
  );
}

function TrackingSection({ t }: { t: NonNullable<PerformanceResponse["tracking"]> }) {
  const rows: [string, TrackingGroup][] = [];
  if (t.groups.oneri) rows.push(["Tüm model önerileri", t.groups.oneri]);
  for (const [k, g] of Object.entries(t.groups)) {
    if (k.startsWith("oneri:")) rows.push([`Öneri · ${t.family_labels[k.slice(6)] ?? k.slice(6)}`, g]);
  }
  for (const [k, g] of Object.entries(t.groups)) {
    if (k.startsWith("kupon:")) rows.push([`Kupon · ${KIND[k.slice(6)] ?? k.slice(6)}`, g]);
  }
  return (
    <section>
      <SectionTitle right={<span className="kicker">ileriye dönük · {dateTime(t.updated_at)}</span>}>Öneri ve kupon takibi</SectionTitle>
      {rows.length === 0 ? (
        <EmptyState title="Henüz başlamış maç yok">Öneriler ve kupon seçimleri maç başladıkça kapanış oranıyla, bitince sonuçla karşılaştırılır.</EmptyState>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Grup</th>
                <th className="px-2 py-2 text-right font-medium">Seçim</th>
                <th className="px-2 py-2 text-right font-medium" title="Alınan oran / kapanış oranı − 1">CLV ort.</th>
                <th className="px-2 py-2 text-right font-medium" title="Kapanış oranından yüksek alınan seçim oranı">Kapanışı yenen</th>
                <th className="px-2 py-2 text-right font-medium">Sonuçlanan</th>
                <th className="px-2 py-2 text-right font-medium" title="Gerçekleşen / modelin beklediği isabet">İsabet / beklenen</th>
                <th className="px-4 py-2 text-right font-medium" title="1 birim düz bahisle">ROI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {rows.map(([label, g]) => (
                <TrackRow key={label} label={label} g={g} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-xs leading-relaxed text-muted">
        CLV (kapanış oranına karşı değer): önerinin yayınlandığı oran, maç başlamadan önceki son orandan yüksekse piyasa sonradan
        modelin tarafına kaymış demektir. Gerçek avantajın en hızlı göstergesidir; pozitif ortalama CLV iyi işarettir.
      </p>
      {t.recent_picks.length > 0 && (
        <div className="panel mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Maç</th>
                <th className="px-2 py-2 font-medium">Öneri</th>
                <th className="px-2 py-2 text-right font-medium">Oran → kapanış</th>
                <th className="px-2 py-2 text-right font-medium">CLV</th>
                <th className="px-4 py-2 font-medium">Sonuç</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {t.recent_picks.slice(0, 25).map((p) => (
                <tr key={`${p.match_id}-${p.label}`}>
                  <td className="px-4 py-1.5">
                    <span className="num text-xs text-muted">{dateTime(p.date_utc)}</span> {p.home} – {p.away}
                  </td>
                  <td className="px-2 py-1.5 text-ink-2">
                    {marketLine(p.label, p.line)}: <b className="text-ink">{p.name}</b> <span className="num text-muted">({pct(p.p_model)})</span>
                  </td>
                  <td className="num px-2 py-1.5 text-right">
                    {odd(p.odd)} → {p.close_odd == null ? "–" : odd(p.close_odd)}
                  </td>
                  <td className={`num px-2 py-1.5 text-right ${p.clv_odds == null ? "" : p.clv_odds > 0 ? "text-good-ink" : "text-critical-ink"}`}>
                    {p.clv_odds == null ? "–" : signedPct(p.clv_odds)}
                  </td>
                  <td className={`px-4 py-1.5 text-xs ${p.result === "won" ? "text-good-ink" : p.result === "lost" ? "text-critical-ink" : "text-muted"}`}>
                    {p.result === "won" ? "✓ tuttu" : p.result === "lost" ? "✕ yattı" : p.result === "void" ? "↺ iade" : "● bekliyor"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LivePicksSection({ s }: { s: NonNullable<PerformanceResponse["live_picks"]> }) {
  const tone = (v: number | null) => (v == null ? "" : v > 0 ? "text-good-ink" : v < 0 ? "text-critical-ink" : "");
  return (
    <section>
      <SectionTitle right={<span className="kicker">{s.n} öneri · {s.settled} sonuçlandı</span>}>Canlı öneriler</SectionTitle>
      {s.n === 0 ? (
        <EmptyState title="Henüz canlı öneri kaydı yok">Maçlar oynanırken kriterlere uyan canlı seçimler 15 dakikada bir kaydedilir.</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="panel grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">
            <Stat label="İsabet" value={s.hit_rate == null ? "–" : pct(s.hit_rate)} sub={`model beklentisi ${s.expected_hit_rate == null ? "–" : pct(s.expected_hit_rate)}`} />
            <Stat label="ROI (1 birim)" value={<span className={tone(s.roi)}>{s.roi == null ? "–" : signedPct(s.roi)}</span>} sub={`${s.won}/${s.settled} tuttu`} />
            {Object.entries(s.by_market).slice(0, 2).map(([k, g]) => (
              <Stat key={k} label={k} value={g.hit_rate == null ? "–" : pct(g.hit_rate)} sub={`${g.won}/${g.n} · ROI ${g.roi == null ? "–" : signedPct(g.roi)}`} />
            ))}
          </div>
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Maç</th>
                  <th className="px-2 py-2 font-medium">Dakika · skor</th>
                  <th className="px-2 py-2 font-medium">Seçim</th>
                  <th className="px-2 py-2 text-right font-medium">Oran · model</th>
                  <th className="px-4 py-2 font-medium">Sonuç</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {s.recent.slice(0, 25).map((r) => (
                  <tr key={`${r.match_id}-${r.market}-${r.sov}-${r.outcome}`}>
                    <td className="px-4 py-1.5">{r.home} – {r.away}</td>
                    <td className="num px-2 py-1.5 text-ink-2">{r.minute}&apos; · {r.score}</td>
                    <td className="px-2 py-1.5">{r.market}{r.sov && !r.sov.includes(":") ? ` ${r.sov}` : ""}: <b>{r.outcome === "0" ? "X" : r.outcome}</b></td>
                    <td className="num px-2 py-1.5 text-right">{odd(r.odd)} · {pct(r.p_model)}</td>
                    <td className={`px-4 py-1.5 text-xs ${r.status === "won" ? "text-good-ink" : r.status === "lost" ? "text-critical-ink" : "text-muted"}`}>
                      {r.status === "won" ? "✓ tuttu" : r.status === "lost" ? "✕ yattı" : r.status === "void" ? "↺ iade" : "● bekliyor"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
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
