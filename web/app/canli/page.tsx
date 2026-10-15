import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import LiveBoard from "@/components/live/LiveBoard";
import { EmptyState, PageHeader, SkeletonRows } from "@/components/ui";
import type { LiveBase } from "@/lib/live-feed";
import { BackendError, getJSON } from "@/lib/server-api";
import type { CouponsResponse } from "@/lib/types";

async function LiveData() {
  let base: LiveBase;
  let coupons: CouponsResponse | null = null;
  try {
    base = await getJSON<LiveBase>("/api/live/base");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Canlı taban verisi alınamadı."} />;
  }
  try {
    coupons = await getJSON<CouponsResponse>("/api/coupons?days=3");
  } catch {
    coupons = null; // kupon takibi olmadan da canlı skorlar çalışır
  }
  if (base.items.length === 0) {
    return <EmptyState title="Bugün takip edilecek maç yok">Model kapsamındaki maçlar 30 saat içinde başlıyorsa burada görünür.</EmptyState>;
  }
  return <LiveBoard base={base} coupons={coupons?.coupons ?? []} />;
}

export default function LivePage() {
  return (
    <>
      <PageHeader kicker="ESPN skor · iddaa canlı oran · canlı model" title="Canlı" />
      <Suspense fallback={<SkeletonRows n={6} h={160} />}>
        <LiveData />
      </Suspense>
    </>
  );
}
