import { Stat } from "@/components/ui";
import { pct, relative } from "@/lib/format";
import { bayiLine, KIND_SHORT, outLabel } from "@/lib/toto";
import type { TotoCouponSlot } from "@/lib/types";

const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 });
const tl2 = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 });

/** Haftanın bir kuponu: özet, kalabalığa göre neden farklı, bayi satırı. Kupon yoksa nedeni. */
export default function TotoCouponCard({ slot }: { slot: TotoCouponSlot }) {
  const c = slot.coupon;
  if (!c) {
    return (
      <section className="panel rise flex flex-col gap-2 p-5" aria-label={slot.title}>
        <p className="kicker">{KIND_SHORT[slot.kind]}</p>
        <h3 className="font-display text-lg font-extrabold uppercase">{slot.title}</h3>
        <p className="text-sm text-ink-2">{slot.description}</p>
        <p className="mt-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">
          ⚠ Bu hafta kurulmadı: {slot.reason ?? "neden bilinmiyor"}
        </p>
      </section>
    );
  }
  const settled = c.status === "settled" && c.hits !== null;
  return (
    <section className="panel rise flex flex-col gap-4 p-5" aria-label={slot.title}>
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-display text-lg font-extrabold uppercase">{slot.title}</h3>
          <span className="text-[0.7rem] text-muted">{c.locked ? "🔒 kilitli" : `güncellendi ${relative(c.updated_at)}`}</span>
        </div>
        <p className="mt-1 text-xs text-ink-2">{slot.description}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Kolon · tutar" value={<span className="num">{c.columns}</span>} sub={`${tl.format(c.cost)} · ${c.column_price} TL/kolon`} />
        <Stat
          label="Beklenen ikramiye"
          value={<span className="num">{c.expected_prize !== null ? tl.format(c.expected_prize) : "–"}</span>}
          sub={
            c.expected_prize !== null
              ? `maliyetin ${(c.expected_prize / c.cost).toFixed(1)} katı${c.expected_prize_se ? ` · ±${tl.format(c.expected_prize_se)}` : ""}`
              : "kalabalık verisi yok"
          }
        />
        <Stat label="15 bilme" value={<span className="num">{pct(c.p15, 3)}</span>} sub={`en az 14: ${pct(c.p_at_least["14"] ?? 0, 2)}`} />
        <Stat
          label="En az 12"
          value={<span className="num">{pct(c.p_at_least["12"] ?? 0, 1)}</span>}
          sub={`beklenen doğru ${c.expected_hits.toFixed(1)}`}
        />
      </div>
      {settled && (
        <p className={`text-sm ${c.hits !== null && c.hits >= 12 ? "text-good-ink" : "text-ink-2"}`}>
          Sonuç: <b className="num">{c.hits}/15</b> · ikramiye <b className="num">{tl2.format(c.prize ?? 0)}</b>
        </p>
      )}
      {c.why && (
        <div className="text-xs text-ink-2">
          <p className="kicker mb-1">Kalabalığa göre neden farklı</p>
          <p>{c.why}</p>
          {c.diffs && c.diffs.length > 0 && (
            <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[0.7rem] text-muted">
              {c.diffs.map((d) => (
                <li key={d.event_no} className="num">
                  {d.event_no}: {d.from.map(outLabel).join("")} → {d.to.map(outLabel).join("")}
                  {d.added.length > 0 &&
                    ` (+${d.added.map((a) => `${outLabel(a.o)} %${Math.round(a.crowd * 100)} oynanıyor`).join(", ")})`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="mt-auto rounded-lg bg-surface-2 px-3 py-2">
        <p className="kicker mb-1">Kupon (bayide doldurmak için)</p>
        <p className="num break-words text-sm">{bayiLine(c.events)}</p>
      </div>
      {c.n_no_data > 0 && (
        <p className="text-xs text-critical-ink">⚠ {c.n_no_data} maç için ne model ne oran bulunabildi; olasılıklar eşit alındı.</p>
      )}
    </section>
  );
}
