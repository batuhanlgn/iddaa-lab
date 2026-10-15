import { Suspense } from "react";
import CouponBuilder from "@/components/coupons/CouponBuilder";
import CouponCard from "@/components/coupons/CouponCard";
import CouponHistory from "@/components/coupons/CouponHistory";
import ErrorPanel from "@/components/ErrorPanel";
import { PageHeader, SectionTitle, SkeletonRows } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { CouponHistoryResponse, CouponsResponse } from "@/lib/types";

const FAM: Record<string, string> = { ms: "Maç sonucu", au: "Alt/Üst", kg: "KG", iy: "İlk yarı", korner: "Korner" };

async function Generated() {
  let data: CouponsResponse;
  try {
    data = await getJSON<CouponsResponse>("/api/coupons?days=3");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Kuponlar üretilemedi."} />;
  }
  const fams = Object.entries(data.family_validation);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
        <span>
          Üretim: {dateTime(data.created_at)} · {data.n_matches_considered} maç tarandı · {data.n_candidates} aday seçim
        </span>
        <span className={data.blend_validated ? "text-good-ink" : "text-warn"}>
          · Harman {data.blend_validated ? "✓ ileriye dönük doğrulandı" : "henüz doğrulanmadı (değer kuponları kapalı)"}
        </span>
        <span className="text-muted">· Kupona açık pazar aileleri:</span>
        {fams.length === 0 ? (
          <span className="text-warn">Backtest henüz çalışmadı: hiçbir aile doğrulanmadı.</span>
        ) : (
          fams.map(([k, v]) => (
            <span key={k} className={`rounded border px-1.5 py-0.5 ${v.validated ? "border-good/40 text-good-ink" : "border-line text-muted line-through"}`}>
              {v.validated ? "✓" : "✕"} {FAM[k] ?? k}
            </span>
          ))
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        {data.coupons.map((c, i) => (
          <CouponCard key={c.kind} c={c} delay={i * 60} />
        ))}
      </div>
    </div>
  );
}

async function History() {
  let data: CouponHistoryResponse;
  try {
    data = await getJSON<CouponHistoryResponse>("/api/coupons/history");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Kupon geçmişi alınamadı."} />;
  }
  return <CouponHistory data={data} />;
}

export default function CouponsPage() {
  return (
    <>
      <PageHeader kicker="Önümüzdeki 72 saat · iddaa oranlarıyla" title="Kuponlar" />
      <div className="flex flex-col gap-10">
        <section>
          <SectionTitle right={<span className="kicker">maç başına tek seçim · MBS uygulanır</span>}>Model kuponları</SectionTitle>
          <Suspense fallback={<SkeletonRows n={3} h={160} />}>
            <Generated />
          </Suspense>
        </section>
        <section>
          <SectionTitle right={<span className="kicker">bu tarayıcıda saklanır</span>}>Kendi kuponun</SectionTitle>
          <CouponBuilder />
        </section>
        <section>
          <SectionTitle right={<span className="kicker">1 sanal birim · ileriye dönük</span>}>Kupon geçmişi ve isabet</SectionTitle>
          <Suspense fallback={<SkeletonRows n={4} h={56} />}>
            <History />
          </Suspense>
        </section>
      </div>
    </>
  );
}
