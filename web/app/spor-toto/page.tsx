import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import TotoBacktestSection from "@/components/TotoBacktestSection";
import TotoCrowdBacktestSection from "@/components/TotoCrowdBacktestSection";
import TotoCouponCard from "@/components/toto/TotoCouponCard";
import TotoMatchBoard from "@/components/toto/TotoMatchBoard";
import { EmptyState, PageHeader, SkeletonRows } from "@/components/ui";
import { dateTime, relative } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { TotoBacktestResponse, TotoCrowdBacktestResponse, TotoKind, TotoResponse } from "@/lib/types";

const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 });
const tl2 = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 });
const mn = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });

const KIND_NAME: Record<TotoKind, string> = { olasilik: "Kupon 1", kalabalik: "Kupon 2", kalabalik_2: "Kupon 3" };

async function Toto() {
  let data: TotoResponse;
  try {
    data = await getJSON<TotoResponse>("/api/toto");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Spor Toto verisi alınamadı."} />;
  }
  const { week, coupons, crowd, history, pool } = data;
  if (!week) {
    return (
      <EmptyState title="Spor Toto programı yok">
        Haftalık program iddaa Spor Toto servisinden her güncellemede çekilir. Henüz açık bir hafta alınamadı.
      </EmptyState>
    );
  }
  const anyCoupon = coupons.some((s) => s.coupon !== null);
  const market = coupons.find((s) => s.coupon?.market)?.coupon?.market;
  const settledKinds = (Object.keys(history.by_kind) as TotoKind[]).filter((k) => history.by_kind[k].settled > 0);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-ink-2">
        <span>
          <b className="text-ink">{week.cycle_no}. hafta</b> · {week.program_name ?? ""}
        </span>
        <span>
          Son oynama: <b className="num text-ink">{dateTime(week.payin_end_utc)}</b>
        </span>
        <span>
          Haftalık toplam: <b className="num text-ink">{tl.format(data.weekly_cost)}</b>{" "}
          <span className="text-muted">/ en fazla {tl.format(pool.weekly_budget)}</span>
        </span>
      </div>

      {crowd && !crowd.available && (
        <div className="rounded-lg border border-warn/50 bg-warn/10 px-4 py-3 text-sm text-warn" role="status">
          ⚠ Kalabalık (oynanma oranı) verisi yok: {crowd.reason ?? "kaynak erişilemedi"} Kupon 2 ve 3 bu hafta kurulmadı; Kupon 1 her
          durumda kurulur.
        </div>
      )}

      {anyCoupon ? (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            {coupons.map((s) => (
              <TotoCouponCard key={s.kind} slot={s} />
            ))}
          </div>
          <TotoMatchBoard slots={coupons} />
          <div className="flex flex-col gap-1 text-[0.7rem] text-muted">
            <p>
              Kuponlar kapanıştan 1 saat önce ayrı ayrı kilitlenir; o zamana kadar her güncellemede en taze olasılıklar ve oynanma
              oranlarıyla yeniden kurulur. {pool.source === "varsayılan" && "Kolon bedeli canlı ayardan okunamadı; bilinen son değer (10 TL) kullanıldı."}
            </p>
            {crowd?.available && (
              <p>
                Oynanma oranı: {crowd.source}
                {crowd.tk_name ? ` · ${crowd.tk_name}` : ""} · son okuma {relative(crowd.fetched_at)}. Beklenen ikramiye: sonuçlar
                bizim olasılıklarımızla, kalabalığın kolonları oynanma oranlarıyla bağımsız sayılarak hesaplanır; kazanan kolon başına
                ödeme = havuz × E[1/(1+diğer kazananlar)].
              </p>
            )}
            {market && (
              <p>
                Tahmin (yalnız önceki {market.n_weeks} haftadan): etkin kalabalık{" "}
                <span className="num">{mn.format(market.n_columns / 1e6)} milyon</span> kolon · havuz 15:{" "}
                <span className="num">{tl.format(market.pools["15"] ?? 0)}</span>
                {market.carry > 0 && <> (devir {tl.format(market.carry)} dahil)</>} · 14: <span className="num">{tl.format(market.pools["14"] ?? 0)}</span> · 13:{" "}
                <span className="num">{tl.format(market.pools["13"] ?? 0)}</span> · 12: <span className="num">{tl.format(market.pools["12"] ?? 0)}</span> ·
                sonuç olasılığı bizim olasılık<sup>a</sup> × oynanma<sup>1−a</sup>, a = <span className="num">{market.blend_a.toFixed(1)}</span>{" "}
                {`(${market.blend_weeks} haftadan; bizim model kalabalığı şaşırtan sonuçları gerçekte olduğundan sık görüyor)`}
                {market.notes.length > 0 && ` · ${market.notes.join(" · ")}`}
              </p>
            )}
          </div>
        </>
      ) : (
        <EmptyState title="Bu hafta kupon üretilmedi">
          {coupons[0]?.reason ?? "Program alındı ama kupon, kapanış geçtiği için ya da güncelleme o saatte çalışmadığı için kurulamadı."}
        </EmptyState>
      )}

      {settledKinds.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-xs text-muted">
          {settledKinds.map((k) => {
            const h = history.by_kind[k];
            return (
              <li key={k}>
                {KIND_NAME[k]}: sonuçlanan {h.settled} hafta · ortalama doğru <span className="num">{(h.avg_hits ?? 0).toFixed(1)}</span> · en
                iyi <span className="num">{h.best_hits}</span> · maliyet <span className="num">{tl.format(h.total_cost)}</span> · ikramiye{" "}
                <span className="num">{tl2.format(h.total_prize)}</span>
              </li>
            );
          })}
        </ul>
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

async function TotoCrowdBacktest() {
  let bt: TotoCrowdBacktestResponse;
  try {
    bt = await getJSON<TotoCrowdBacktestResponse>("/api/toto/crowd-backtest");
  } catch (e) {
    if (e instanceof BackendError && e.status === 404) return null;
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Üç kupon backtest sonucu alınamadı."} />;
  }
  if (!bt.available) {
    return (
      <EmptyState title="Üç kupon backtest'i henüz çalışmadı">
        Kalabalık kuponlarının geçmiş sınaması haftalık backtest işinde, Spor Toto backtest&apos;inden sonra çalışır.
      </EmptyState>
    );
  }
  return <TotoCrowdBacktestSection bt={bt} />;
}

export default function TotoPage() {
  return (
    <>
      <PageHeader kicker="Haftalık · 3 kupon · her biri en fazla 3.000 TL" title="Spor Toto" />
      <Suspense fallback={<SkeletonRows n={8} h={48} />}>
        <Toto />
      </Suspense>
      <div className="mt-10">
        <Suspense fallback={<SkeletonRows n={4} h={48} />}>
          <TotoCrowdBacktest />
        </Suspense>
      </div>
      <div className="mt-10">
        <Suspense fallback={<SkeletonRows n={4} h={48} />}>
          <TotoBacktest />
        </Suspense>
      </div>
    </>
  );
}
