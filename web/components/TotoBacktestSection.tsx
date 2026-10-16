import { pct, signedPct } from "@/lib/format";
import type { TotoBacktestResponse, TotoBtStrategy } from "@/lib/types";
import { SectionTitle, Stat } from "./ui";

type Bt = Extract<TotoBacktestResponse, { available: true }>;

const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 });

const STRAT_LABEL: Record<string, string> = {
  canli: "Bugünkü mantık (model + oran)",
  piyasa: "Yalnız oran (marjsız)",
  model: "Yalnız model",
  rastgele: "Rastgele (200 tekrar, medyan)",
};

function tone(v: number): string {
  return v > 0 ? "text-good-ink" : v < 0 ? "text-critical-ink" : "";
}

function StratRow({ k, s }: { k: string; s: TotoBtStrategy }) {
  const random = k === "rastgele";
  const roi = random && s.roi_p50 !== undefined ? s.roi_p50 : s.roi;
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="px-4 py-1.5 font-medium">{STRAT_LABEL[k] ?? k}</td>
      <td className="num px-2 py-1.5 text-right">{tl.format(s.cost)}</td>
      <td className="num px-2 py-1.5 text-right">{random && s.prize_p50 !== undefined ? tl.format(s.prize_p50) : tl.format(s.prize)}</td>
      <td className={`num px-2 py-1.5 text-right ${tone(roi)}`}>
        {signedPct(roi)}
        {random && s.roi_p05 !== undefined && s.roi_p95 !== undefined && (
          <span className="block text-[0.65rem] text-muted">
            %90: {signedPct(s.roi_p05)} … {signedPct(s.roi_p95)}
          </span>
        )}
      </td>
      <td className="num px-2 py-1.5 text-right">{s.avg_hits.toFixed(1)}</td>
      <td className="num px-2 py-1.5 text-right">{random ? s.weeks_12plus.toFixed(1) : s.weeks_12plus}</td>
      <td className="num px-2 py-1.5 text-right">{random ? s.weeks_13plus.toFixed(2) : s.weeks_13plus}</td>
      <td className="num px-2 py-1.5 text-right">{random ? s.weeks_14plus.toFixed(2) : s.weeks_14plus}</td>
      <td className="num px-4 py-1.5 text-right">{random ? s.weeks_15.toFixed(3) : s.weeks_15}</td>
    </tr>
  );
}

export default function TotoBacktestSection({ bt }: { bt: Bt }) {
  const live = bt.strategies.canli;
  const cal = bt.calibration;
  const sm = cal.same_matches;
  return (
    <section className="rise">
      <SectionTitle right={<span className="kicker">{bt.window.n_weeks} geçmiş hafta · walk-forward</span>}>Backtest</SectionTitle>
      <div className="panel flex flex-col gap-5 p-5">
        <p className="text-sm text-ink-2">
          Bugünkü kupon mantığı {bt.window.from_cycle}–{bt.window.to_cycle}. haftalarda ({bt.window.from.slice(0, 10)} –{" "}
          {bt.window.to.slice(0, 10)}) oynansaydı: her hafta model yalnız o haftadan önceki maçlarla eğitildi, kupon aynı{" "}
          {bt.columns} kolon sınırıyla kuruldu, ikramiye o haftanın gerçek ikramiye tablosundan hesaplandı.
        </p>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Yatırılan" value={<span className="num">{tl.format(live.cost)}</span>} sub={`${live.n_weeks} hafta`} />
          <Stat label="İkramiye" value={<span className="num">{tl.format(live.prize)}</span>} sub={`${live.prize_weeks} haftada ikramiye`} />
          <Stat
            label="Getiri"
            value={<span className={`num ${tone(live.roi)}`}>{signedPct(live.roi)}</span>}
            sub={`net ${tl.format(live.net)}`}
          />
          <Stat
            label="Ortalama doğru"
            value={<span className="num">{live.avg_hits.toFixed(1)}</span>}
            sub={`beklenen ${cal.expected_hits.toFixed(1)} · 12+: ${live.weeks_12plus} hafta · 15: ${live.weeks_15}`}
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Strateji (aynı kolon sınırı)</th>
                <th className="px-2 py-2 text-right font-medium">Maliyet</th>
                <th className="px-2 py-2 text-right font-medium">İkramiye</th>
                <th className="px-2 py-2 text-right font-medium">Getiri</th>
                <th className="px-2 py-2 text-right font-medium">Ort. doğru</th>
                <th className="px-2 py-2 text-right font-medium" title="En az 12 bilinen hafta sayısı">12+</th>
                <th className="px-2 py-2 text-right font-medium">13+</th>
                <th className="px-2 py-2 text-right font-medium">14+</th>
                <th className="px-4 py-2 text-right font-medium">15</th>
              </tr>
            </thead>
            <tbody>
              {(["canli", "piyasa", "model", "rastgele"] as const).map((k) => (
                <StratRow key={k} k={k} s={bt.strategies[k]} />
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg bg-surface-2 p-3 text-sm">
            <p className="kicker mb-2">Olasılık kalitesi (aynı {sm.piyasa.n} maç)</p>
            <ul className="flex flex-col gap-1 text-ink-2">
              {(["piyasa", "harman", "model"] as const).map((k) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>{k === "harman" ? "Model + oran" : k === "piyasa" ? "Yalnız oran" : "Yalnız model"}</span>
                  <span className="num">
                    log-loss {sm[k].logloss.toFixed(3)} · en olası tuttu {pct(sm[k].top_hit, 1)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[0.7rem] text-muted">Düşük log-loss = daha iyi. Model, oranı harmanda iyileştirmiyor, kötüleştiriyor.</p>
          </div>
          <div className="rounded-lg bg-surface-2 p-3 text-sm">
            <p className="kicker mb-2">Kademe çıkan hafta: beklenen / gerçekleşen</p>
            <ul className="flex flex-col gap-1 text-ink-2">
              {["12", "13", "14", "15"].map((t) => (
                <li key={t} className="flex justify-between gap-2">
                  <span>en az {t} doğru</span>
                  <span className="num">
                    {(cal.p_at_least_expected_weeks[t] ?? 0).toFixed(1)} / {cal.p_at_least_observed_weeks[t] ?? 0}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[0.7rem] text-muted">
              İsabet modelin beklediği kadar; kayıp, favori ağırlıklı kuponun kalabalıkla aynı sonuçları tutturup ikramiyeyi çok kişiyle
              paylaşmasından.
            </p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {([["En iyi haftalar", bt.best_weeks], ["En kötü haftalar", bt.worst_weeks]] as const).map(([title, ws]) => (
            <div key={title}>
              <p className="kicker mb-1">{title}</p>
              <ul className="flex flex-col gap-0.5 text-sm">
                {ws.map((w) => (
                  <li key={w.cycle_no} className="flex justify-between gap-2">
                    <span className="truncate">
                      {w.cycle_no}. hafta {w.program_name ? `· ${w.program_name}` : ""}
                    </span>
                    <span className="num shrink-0">
                      {w.hits}/15 · {tl.format(w.prize)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <details>
          <summary className="cursor-pointer text-sm text-ink-2">Tüm haftalar ({bt.weeks.length})</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="px-2 py-1 font-medium">Hafta</th>
                  <th className="px-2 py-1 text-right font-medium">Kolon bedeli</th>
                  <th className="px-2 py-1 text-right font-medium">Doğru</th>
                  <th className="px-2 py-1 text-right font-medium">Maliyet</th>
                  <th className="px-2 py-1 text-right font-medium">İkramiye</th>
                  <th className="px-2 py-1 text-right font-medium" title="ESPN/oran bulunamayan maç sayısı">Veri yok</th>
                </tr>
              </thead>
              <tbody>
                {bt.weeks.map((w) => (
                  <tr key={w.cycle_no} className="border-b border-line/60 last:border-0">
                    <td className="px-2 py-1">
                      {w.cycle_no} <span className="text-xs text-muted">{w.program_name ?? ""}</span>
                    </td>
                    <td className="num px-2 py-1 text-right">{w.column_price} TL</td>
                    <td className="num px-2 py-1 text-right">{w.hits}</td>
                    <td className="num px-2 py-1 text-right">{tl.format(w.cost)}</td>
                    <td className={`num px-2 py-1 text-right ${w.prize > 0 ? "text-good-ink" : "text-muted"}`}>{tl.format(w.prize)}</td>
                    <td className="num px-2 py-1 text-right">{w.n_by_source.yok ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <ul className="flex flex-col gap-1 text-[0.7rem] text-muted">
          {bt.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
          <li>
            • Kolon bedeli:{" "}
            {bt.price_schedule.map((p) => `${p.from_cycle}${p.to_cycle ? `–${p.to_cycle}` : "+"}. hafta ${p.price} TL`).join(" · ")}
          </li>
        </ul>
      </div>
    </section>
  );
}
