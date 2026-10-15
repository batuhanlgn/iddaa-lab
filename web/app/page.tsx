import Link from "next/link";
import { Suspense } from "react";
import BulletinBoard from "@/components/BulletinBoard";
import ErrorPanel from "@/components/ErrorPanel";
import { EmptyState, PageHeader, SkeletonRows } from "@/components/ui";
import { BackendError, getJSON } from "@/lib/server-api";
import type { MatchesResponse } from "@/lib/types";

async function BulletinData() {
  let data: MatchesResponse;
  try {
    data = await getJSON<MatchesResponse>("/api/matches?days=7");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Bülten alınamadı."} />;
  }
  if (data.items.length === 0 && data.market_only.length === 0) {
    return (
      <EmptyState title="Henüz tahmin yok">
        Önümüzdeki 7 gün için hesaplanmış maç bulunamadı. İlk kurulumda veri indirme ve model eğitimi yaklaşık bir saat
        sürer; ilerlemeyi <Link className="underline" href="/veri">Veri</Link> sayfasından izleyebilirsin.
      </EmptyState>
    );
  }
  return <BulletinBoard data={data} nowIso={data.generated_at} />;
}

export default function Home() {
  return (
    <>
      <PageHeader kicker="Önümüzdeki 7 gün · model + iddaa bülteni" title="Maç bülteni" />
      <Suspense fallback={<SkeletonRows n={8} h={88} />}>
        <BulletinData />
      </Suspense>
    </>
  );
}
