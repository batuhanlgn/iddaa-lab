"use client";

import Link from "next/link";
import { useState } from "react";
import { SectionTitle } from "@/components/ui";
import { dateTime, pct } from "@/lib/format";
import { KIND_SHORT, outLabel, pickCode, TOTO_OUTS } from "@/lib/toto";
import type { TotoCoupon, TotoCouponSlot, TotoEvent, TotoKind, TotoOutcome, TotoSource } from "@/lib/types";

const SOURCE_LABEL: Record<TotoSource, { text: string; title: string }> = {
  harman: { text: "model + oran", title: "Model olasılığı iddaa oranıyla harmanlandı" },
  model: { text: "model", title: "iddaa oranı yok; yalnız model" },
  piyasa: { text: "oran", title: "Model kapsamı dışında; iddaa oranından (marjsız)" },
  yok: { text: "veri yok", title: "Ne model ne oran bulunabildi; olasılıklar eşit alındı" },
};

const KIND_STYLE: Record<TotoEvent["kind"], string> = {
  banko: "border-good/50 text-good-ink",
  çift: "border-warn/50 text-warn",
  üçlü: "border-line-strong text-ink-2",
};

type Tab = "karsilastir" | TotoKind;

function MatchName({ ev }: { ev: TotoEvent }) {
  const linkable = ev.match_id !== null && (ev.source === "harman" || ev.source === "model");
  const name = ev.home && ev.away ? `${ev.home} – ${ev.away}` : ev.event_name;
  return (
    <div className="min-w-0">
      {linkable ? (
        <Link href={`/mac/${ev.match_id}`} className="block truncate text-sm font-medium hover:underline">
          {name}
        </Link>
      ) : (
        <span className="block truncate text-sm font-medium">{name}</span>
      )}
      <span className="text-[0.7rem] text-muted">
        {dateTime(ev.kickoff_utc)} · {ev.league_name ?? ev.competition} ·{" "}
        <span title={SOURCE_LABEL[ev.source].title} className={ev.source === "yok" ? "text-critical-ink" : ""}>
          {SOURCE_LABEL[ev.source].text}
        </span>
        {ev.confidence === "düşük" && <span className="text-warn"> · düşük güven</span>}
      </span>
    </div>
  );
}

function Triple({ v, label }: { v: Record<TotoOutcome, number> | null; label: string }) {
  if (!v) return <span className="text-muted">{label}: –</span>;
  return (
    <span>
      {label}: <span className="num">{TOTO_OUTS.map((o) => Math.round(v[o] * 100)).join(" · ")}</span>
    </span>
  );
}

function PickChip({ ev }: { ev: TotoEvent | undefined }) {
  if (!ev) return <span className="text-muted">–</span>;
  const hit = ev.winner === null ? null : ev.picks.includes(ev.winner);
  return (
    <span
      className={`num inline-block min-w-[2.6rem] rounded-md border px-1.5 py-0.5 text-center text-xs font-semibold ${
        hit === null ? "border-accent/60 bg-accent/10" : hit ? "border-good bg-good/15 text-good-ink" : "border-critical/50 text-critical-ink"
      }`}
      title={hit === null ? `kapsama ${pct(ev.cover)}` : hit ? "tuttu" : "tutmadı"}
    >
      {pickCode(ev.picks)}
    </span>
  );
}

function CompareTable({ base, coupons }: { base: TotoCoupon; coupons: Partial<Record<TotoKind, TotoCoupon>> }) {
  // Yalnız üretilen kupon türleri (kalabalık kuponları kapalıyken tek sütun)
  const kinds = (["olasilik", "kalabalik", "kalabalik_2"] as const).filter((k): k is TotoKind => coupons[k] !== undefined);
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[540px]">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="px-2 py-2 font-medium">#</th>
            <th className="px-2 py-2 text-left font-medium">Maç</th>
            <th className="px-2 py-2 text-left font-medium" title="1 · X · 2 yüzdeleri">
              Olasılık / oynanma
            </th>
            {kinds.map((k) => (
              <th key={k} className="px-1 py-2 font-medium">
                {KIND_SHORT[k]}
              </th>
            ))}
            <th className="px-2 py-2 text-right font-medium">Sonuç</th>
          </tr>
        </thead>
        <tbody>
          {base.events.map((ev, i) => (
            <tr key={ev.event_no} className="border-b border-line/60 last:border-0">
              <td className="num px-2 py-1.5 text-center text-sm font-semibold">{ev.event_no}</td>
              <td className="max-w-[14rem] px-2 py-1.5">
                <MatchName ev={ev} />
              </td>
              <td className="whitespace-nowrap px-2 py-1.5 text-[0.7rem] leading-tight text-ink-2">
                <div>
                  <Triple v={ev.probs} label="olas." />
                </div>
                <div>
                  <Triple v={ev.crowd} label="oyn." />
                </div>
              </td>
              {kinds.map((k) => (
                <td key={k} className="px-1 py-1.5 text-center">
                  <PickChip ev={coupons[k]?.events[i]} />
                </td>
              ))}
              <td className="num px-2 py-1.5 text-right text-xs">{ev.result ? `${ev.winner ? outLabel(ev.winner) : "?"} (${ev.result})` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OutcomeCell({ ev, o }: { ev: TotoEvent; o: TotoOutcome }) {
  const picked = ev.picks.includes(o);
  const won = ev.winner === o;
  return (
    <td className="px-1 py-1.5 text-center">
      <span
        className={`num inline-flex min-w-[3.6rem] flex-col items-center rounded-md border px-1.5 py-1 text-xs ${
          picked ? "border-accent bg-accent/15 font-semibold text-ink" : "border-line text-ink-2"
        } ${won ? "ring-2 ring-good" : ""}`}
        title={`${outLabel(o)}: olasılık ${pct(ev.probs[o], 1)}${ev.crowd ? ` · oynanma ${pct(ev.crowd[o], 0)}` : ""}${
          ev.odds ? ` · iddaa ${ev.odds[o].toFixed(2)}` : ""
        }`}
      >
        <span>
          {picked ? "✓ " : ""}
          {outLabel(o)}
        </span>
        <span className="text-[0.7rem]">{pct(ev.probs[o])}</span>
        {ev.crowd && <span className="text-[0.62rem] text-muted">oyn. {pct(ev.crowd[o])}</span>}
      </span>
      {won && <span className="sr-only">(sonuç)</span>}
    </td>
  );
}

function DetailTable({ c }: { c: TotoCoupon }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px]">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="px-2 py-2 font-medium">#</th>
            <th className="px-2 py-2 text-left font-medium">Maç</th>
            <th className="px-1 py-2 font-medium">1</th>
            <th className="px-1 py-2 font-medium">X</th>
            <th className="px-1 py-2 font-medium">2</th>
            <th className="px-2 py-2 font-medium">Tür</th>
            <th className="px-2 py-2 text-right font-medium" title="İşaretlenen sonuçların toplam olasılığı">
              Kapsama
            </th>
          </tr>
        </thead>
        <tbody>
          {c.events.map((ev) => {
            const hit = ev.winner === null ? null : ev.picks.includes(ev.winner);
            return (
              <tr key={ev.event_no} className="border-b border-line/60 last:border-0">
                <td className="num px-2 py-1.5 text-center text-sm font-semibold">{ev.event_no}</td>
                <td className="max-w-[16rem] px-2 py-1.5">
                  <MatchName ev={ev} />
                </td>
                {TOTO_OUTS.map((o) => (
                  <OutcomeCell key={o} ev={ev} o={o} />
                ))}
                <td className="px-2 py-1.5 text-center">
                  <span className={`inline-block rounded border px-1.5 py-0.5 text-[0.7rem] font-medium ${KIND_STYLE[ev.kind]}`}>{ev.kind}</span>
                </td>
                <td className="num px-2 py-1.5 text-right text-xs">
                  {ev.result ? (
                    <span className={hit ? "text-good-ink" : "text-critical-ink"}>
                      {hit ? "✓" : "✗"} {ev.result}
                    </span>
                  ) : (
                    <span className="text-muted">{pct(ev.cover)}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 15 maç: üç kuponun işaretleri ve oynanma oranları yan yana; sekmeyle tek kuponun ayrıntısı. */
export default function TotoMatchBoard({ slots }: { slots: TotoCouponSlot[] }) {
  const [tab, setTab] = useState<Tab>("karsilastir");
  const coupons: Partial<Record<TotoKind, TotoCoupon>> = {};
  for (const s of slots) if (s.coupon) coupons[s.kind] = s.coupon;
  const base = coupons.olasilik ?? slots.find((s) => s.coupon)?.coupon;
  if (!base) return null;
  const tabs: { key: Tab; label: string }[] = [
    { key: "karsilastir", label: "Üç kupon" },
    ...slots.filter((s) => s.coupon).map((s) => ({ key: s.kind as Tab, label: s.title })),
  ];
  const active = tab === "karsilastir" ? null : coupons[tab];
  return (
    <section className="rise">
      <SectionTitle right={<span className="kicker">olas. = bizim olasılık · oyn. = kalabalığın oynama yüzdesi</span>}>15 maç</SectionTitle>
      <div className="mb-3 flex gap-1 overflow-x-auto" role="tablist" aria-label="Kupon">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t.key ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {active ? <DetailTable c={active} /> : <CompareTable base={base} coupons={coupons} />}
    </section>
  );
}
