import Link from "next/link";
import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import TotoBacktestSection from "@/components/TotoBacktestSection";
import { EmptyState, PageHeader, SectionTitle, SkeletonRows, Stat } from "@/components/ui";
import { dateTime, pct, relative } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { TotoBacktestResponse, TotoCoupon, TotoEvent, TotoOutcome, TotoResponse, TotoSource } from "@/lib/types";

const OUTS: TotoOutcome[] = ["1", "0", "2"];
const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 });
const tl2 = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 });

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

function OutcomeCell({ ev, o }: { ev: TotoEvent; o: TotoOutcome }) {
  const picked = ev.picks.includes(o);
  const won = ev.winner === o;
  return (
    <td className="px-1 py-1.5 text-center">
      <span
        className={`num inline-flex min-w-[3.4rem] flex-col items-center rounded-md border px-1.5 py-1 text-xs ${
          picked ? "border-accent bg-accent/15 font-semibold text-ink" : "border-line text-ink-2"
        } ${won ? "ring-2 ring-good" : ""}`}
        title={`${o === "0" ? "X" : o}: olasılık ${pct(ev.probs[o], 1)}${ev.odds ? ` · iddaa ${ev.odds[o].toFixed(2)}` : ""}`}
      >
        <span>
          {picked ? "✓ " : ""}
          {o === "0" ? "X" : o}
        </span>
        <span className="text-[0.7rem]">{pct(ev.probs[o])}</span>
      </span>
      {won && <span className="sr-only">(sonuç)</span>}
    </td>
  );
}

function EventRow({ ev }: { ev: TotoEvent }) {
  const linkable = ev.match_id !== null && (ev.source === "harman" || ev.source === "model");
  const name = ev.home && ev.away ? `${ev.home} – ${ev.away}` : ev.event_name;
  const hit = ev.winner === null ? null : ev.picks.includes(ev.winner);
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="num px-2 py-1.5 text-center text-sm font-semibold">{ev.event_no}</td>
      <td className="px-2 py-1.5">
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
      </td>
      {OUTS.map((o) => (
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
}

function CouponSummary({ c }: { c: TotoCoupon }) {
  // Bayi formundaki sıra: 1, X, 2
  const code = c.events
    .map((e) => `${e.event_no}: ${OUTS.filter((o) => e.picks.includes(o)).map((o) => (o === "0" ? "X" : o)).join("")}`)
    .join(" · ");
  return (
    <section className="panel rise p-5">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Kolon" value={<span className="num">{c.columns}</span>} sub={`${c.column_price} TL / kolon`} />
        <Stat label="Tutar" value={<span className="num">{tl.format(c.cost)}</span>} sub={`bütçe ${tl.format(c.budget)}`} />
        <Stat label="15 bilme" value={<span className="num">{pct(c.p15, 2)}</span>} sub={`en az 12: ${pct(c.p_at_least["12"] ?? 0)}`} />
        <Stat
          label="Beklenen doğru"
          value={<span className="num">{c.expected_hits.toFixed(1)}</span>}
          sub={`en az 13: ${pct(c.p_at_least["13"] ?? 0)} · 14: ${pct(c.p_at_least["14"] ?? 0, 1)}`}
        />
      </div>
      <div className="mt-4 rounded-lg bg-surface-2 px-3 py-2">
        <p className="kicker mb-1">Kupon (bayide doldurmak için)</p>
        <p className="num break-words text-sm">{code}</p>
      </div>
      <p className="mt-3 text-[0.7rem] text-muted">
        {c.locked ? "🔒 Kilitli: kapanıştan önceki son hali." : `Kapanıştan 1 saat önce kilitlenir; o zamana kadar her güncellemede yenilenir (son: ${relative(c.updated_at)}).`}{" "}
        {c.pool_source === "varsayılan" && "Kolon bedeli canlı ayardan okunamadı; bilinen son değer (10 TL) kullanıldı. "}
        Kupon, bütçe içinde 15 maçı da bilme olasılığını en büyütür: belirsiz maçlara çift/üçlü, net maçlara banko. Oynanma
        oranları (ikramiyenin kaç kişiyle paylaşılacağı) hesaba katılmaz.
      </p>
      {c.n_no_data > 0 && (
        <p className="mt-2 text-xs text-critical-ink">
          ⚠ {c.n_no_data} maç için ne model ne oran bulunabildi; bu maçlarda olasılıklar eşit alındı.
        </p>
      )}
    </section>
  );
}

async function Toto() {
  let data: TotoResponse;
  try {
    data = await getJSON<TotoResponse>("/api/toto");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Spor Toto verisi alınamadı."} />;
  }
  const { week, coupon, history } = data;
  if (!week) {
    return (
      <EmptyState title="Spor Toto programı yok">
        Haftalık program iddaa Spor Toto servisinden her güncellemede çekilir. Henüz açık bir hafta alınamadı.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-ink-2">
        <span>
          <b className="text-ink">{week.cycle_no}. hafta</b> · {week.program_name ?? ""}
        </span>
        <span>
          Son oynama: <b className="num text-ink">{dateTime(week.payin_end_utc)}</b>
        </span>
        {coupon?.status === "settled" && coupon.hits !== null && (
          <span className={coupon.hits >= 12 ? "text-good-ink" : ""}>
            Sonuç: <b className="num">{coupon.hits}/15</b> · ikramiye <b className="num">{tl2.format(coupon.prize ?? 0)}</b>
          </span>
        )}
      </div>

      {coupon ? (
        <>
          <CouponSummary c={coupon} />
          <section className="rise">
            <SectionTitle right={<span className="kicker">✓ = işaretli · çerçeve = sonuç</span>}>15 maç</SectionTitle>
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
                  {coupon.events.map((ev) => (
                    <EventRow key={ev.event_no} ev={ev} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <EmptyState title="Bu hafta kupon üretilmedi">
          Program alındı ama kupon, kapanış geçtiği için ya da güncelleme o saatte çalışmadığı için kurulamadı.
        </EmptyState>
      )}

      {history.settled > 0 && (
        <p className="text-xs text-muted">
          Sonuçlanan {history.settled} hafta · ortalama doğru{" "}
          <span className="num">{(history.avg_hits ?? 0).toFixed(1)}</span> · en iyi <span className="num">{history.best_hits}</span> · toplam
          maliyet <span className="num">{tl.format(history.total_cost)}</span> · toplam ikramiye{" "}
          <span className="num">{tl2.format(history.total_prize)}</span>
        </p>
      )}
    </div>
  );
}

async function TotoBacktest() {
  let bt: TotoBacktestResponse;
  try {
    bt = await getJSON<TotoBacktestResponse>("/api/toto/backtest");
  } catch (e) {
    // Bölüm, backtest yayınlanmadan önce dışa aktarılmış veride yoktur; diğer hatalar kullanıcıya gösterilir
    if (e instanceof BackendError && e.status === 404) return null;
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Spor Toto backtest sonucu alınamadı."} />;
  }
  if (!bt.available) {
    return (
      <EmptyState title="Backtest henüz çalışmadı">
        Spor Toto backtest&apos;i haftalık backtest işinde (pazartesi) çalışır; ilk sonuç geldiğinde burada görünür.
      </EmptyState>
    );
  }
  return <TotoBacktestSection bt={bt} />;
}

export default function TotoPage() {
  return (
    <>
      <PageHeader kicker="Haftalık · en fazla 3.000 TL" title="Spor Toto" />
      <Suspense fallback={<SkeletonRows n={8} h={48} />}>
        <Toto />
      </Suspense>
      <div className="mt-10">
        <Suspense fallback={<SkeletonRows n={4} h={48} />}>
          <TotoBacktest />
        </Suspense>
      </div>
    </>
  );
}
