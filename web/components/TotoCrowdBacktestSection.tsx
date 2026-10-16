import { signedPct } from "@/lib/format";
import type { TotoCrowdBacktestResponse, TotoCrowdBtKind, TotoKind } from "@/lib/types";
import { SectionTitle } from "./ui";

type Bt = Extract<TotoCrowdBacktestResponse, { available: true }>;

const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 });
const KINDS: TotoKind[] = ["olasilik", "kalabalik", "kalabalik_2"];
const LABEL: Record<TotoKind, string> = {
  olasilik: "Kupon 1 · olasılık",
  kalabalik: "Kupon 2 · kalabalık",
  kalabalik_2: "Kupon 3 · kalabalık (ikinci)",
};

function tone(v: number | null): string {
  if (v === null) return "";
  return v > 0 ? "text-good-ink" : v < 0 ? "text-critical-ink" : "";
}

function ratio(k: TotoCrowdBtKind): string {
  return k.realized_over_expected === null ? "–" : k.realized_over_expected.toFixed(3);
}

function KindRow({ kind, k }: { kind: TotoKind; k: TotoCrowdBtKind }) {
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="px-4 py-1.5 font-medium">{LABEL[kind]}</td>
      <td className="num px-2 py-1.5 text-right">{tl.format(k.cost)}</td>
      <td className="num px-2 py-1.5 text-right">{tl.format(k.prize)}</td>
      <td className={`num px-2 py-1.5 text-right ${tone(k.roi)}`}>{signedPct(k.roi)}</td>
      <td className="num px-2 py-1.5 text-right">
        {tl.format(k.expected_prize)}
        {k.expected_roi !== null && <span className="block text-[0.65rem] text-muted">getiri {signedPct(k.expected_roi)}</span>}
      </td>
      <td className="num px-2 py-1.5 text-right">{ratio(k)}</td>
      <td className="num px-2 py-1.5 text-right">{k.avg_hits.toFixed(1)}</td>
      <td className="num px-2 py-1.5 text-right">
        {k.weeks_12plus} <span className="text-[0.65rem] text-muted">/ {k.p12_expected_weeks.toFixed(1)}</span>
      </td>
      <td className="num px-2 py-1.5 text-right">{k.weeks_13plus}</td>
      <td className="num px-2 py-1.5 text-right">{k.weeks_14plus}</td>
      <td className="num px-4 py-1.5 text-right">
        {k.weeks_15} <span className="text-[0.65rem] text-muted">/ {k.p15_expected_weeks.toFixed(2)}</span>
      </td>
    </tr>
  );
}

/** Üç kuponun (olasılık / kalabalık / kalabalık-2) walk-forward backtest'i: maliyet, ikramiye, beklenen vs gerçekleşen. */
export default function TotoCrowdBacktestSection({ bt }: { bt: Bt }) {
  const k1 = bt.kinds.olasilik;
  const k2 = bt.kinds.kalabalik;
  return (
    <section className="rise">
      <SectionTitle right={<span className="kicker">{bt.window.n_weeks} geçmiş hafta · walk-forward</span>}>
        Üç kupon backtest&apos;i
      </SectionTitle>
      <div className="panel flex flex-col gap-5 p-5">
        <p className="text-sm text-ink-2">
          Oynanma oranı verisi olan {bt.window.from_cycle}–{bt.window.to_cycle}. haftalarda üç kupon da aynı olasılıklarla ve{" "}
          {bt.columns} kolon sınırıyla kuruldu; N ve havuz tahmini yalnız önceki haftalardan, ikramiye o haftanın gerçek ikramiye
          tablosundan. Kupon 2&apos;nin gerçekleşen / beklenen ikramiye oranı <b className="num">{ratio(k2)}</b>, Kupon 1&apos;in{" "}
          <b className="num">{ratio(k1)}</b>: {(k2.realized_over_expected ?? 0) < 0.25
            ? "kalabalık kuponlarının beklenen ikramiyesi bu haftalarda tutmadı; iyimser kabul edin."
            : "kalabalık modeli bu haftalarda kabaca tuttu."}
        </p>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Kupon</th>
                <th className="px-2 py-2 text-right font-medium">Maliyet</th>
                <th className="px-2 py-2 text-right font-medium">İkramiye</th>
                <th className="px-2 py-2 text-right font-medium">Getiri</th>
                <th className="px-2 py-2 text-right font-medium" title="Kalabalık modeline göre, kupon kurulurken">
                  Beklenen ikramiye
                </th>
                <th className="px-2 py-2 text-right font-medium" title="Gerçekleşen / beklenen ikramiye">
                  Gerç./bekl.
                </th>
                <th className="px-2 py-2 text-right font-medium">Ort. doğru</th>
                <th className="px-2 py-2 text-right font-medium" title="En az 12 doğru: gerçekleşen / beklenen hafta">
                  12+
                </th>
                <th className="px-2 py-2 text-right font-medium">13+</th>
                <th className="px-2 py-2 text-right font-medium">14+</th>
                <th className="px-4 py-2 text-right font-medium" title="15 doğru: gerçekleşen / beklenen hafta">
                  15
                </th>
              </tr>
            </thead>
            <tbody>
              {KINDS.map((k) => (
                <KindRow key={k} kind={k} k={bt.kinds[k]} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm text-ink-2">
          Üçü birlikte: maliyet <span className="num">{tl.format(bt.combined.cost)}</span> · ikramiye{" "}
          <span className="num">{tl.format(bt.combined.prize)}</span> · getiri{" "}
          <span className={`num ${tone(bt.combined.roi)}`}>{bt.combined.roi === null ? "–" : signedPct(bt.combined.roi)}</span>
        </p>

        <div className="grid gap-4 md:grid-cols-3">
          {KINDS.map((kind) => {
            const k = bt.kinds[kind];
            return (
              <div key={kind} className="rounded-lg bg-surface-2 p-3 text-sm">
                <p className="kicker mb-2">{LABEL[kind]}: kademe başına beklenen / gerçekleşen</p>
                <ul className="flex flex-col gap-1 text-ink-2">
                  {["15", "14", "13", "12"].map((t) => (
                    <li key={t} className="flex justify-between gap-2">
                      <span>{t} doğru</span>
                      <span className="num">
                        {tl.format(k.expected_by_tier[t] ?? 0)} / {tl.format(k.realized_by_tier[t] ?? 0)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>

        <details>
          <summary className="cursor-pointer text-sm text-ink-2">Tüm haftalar ({bt.weeks.length})</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="px-2 py-1 font-medium">Hafta</th>
                  <th className="px-2 py-1 text-right font-medium" title="Harman ağırlığı (önceki haftalardan)">
                    a
                  </th>
                  {KINDS.map((k) => (
                    <th key={k} className="px-2 py-1 text-right font-medium">
                      {LABEL[k].split(" · ")[0]}: doğru · ikramiye (beklenen)
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bt.weeks.map((w) => (
                  <tr key={w.cycle_no} className="border-b border-line/60 last:border-0">
                    <td className="px-2 py-1">
                      {w.cycle_no} <span className="text-xs text-muted">{w.program_name ?? ""}</span>
                    </td>
                    <td className="num px-2 py-1 text-right">{w.market.blend_a.toFixed(1)}</td>
                    {KINDS.map((k) => {
                      const c = w.coupons[k];
                      return (
                        <td key={k} className="num px-2 py-1 text-right">
                          {c.hits} · <span className={c.prize > 0 ? "text-good-ink" : "text-muted"}>{tl.format(c.prize)}</span>{" "}
                          <span className="text-[0.65rem] text-muted">({tl.format(c.expected_prize)})</span>
                        </td>
                      );
                    })}
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
          {bt.excluded.length > 0 && (
            <li>
              • Dışarıda kalan {bt.excluded.length} hafta:{" "}
              {bt.excluded.map((e) => `${e.cycle_no}${e.reason ? ` (${e.reason})` : ""}`).join("; ")}
            </li>
          )}
          {bt.tk_odds_fallback_events > 0 && <li>• {bt.tk_odds_fallback_events} maçta olasılık totokazan&apos;ın iddaa oranından.</li>}
        </ul>
      </div>
    </section>
  );
}
