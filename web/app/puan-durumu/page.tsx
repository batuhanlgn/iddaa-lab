import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import StandingsBoard from "@/components/StandingsBoard";
import { EmptyState, PageHeader, SkeletonRows } from "@/components/ui";
import { BackendError, getJSON } from "@/lib/server-api";
import type { StandingsResponse } from "@/lib/types";

async function Standings() {
  let data: StandingsResponse;
  try {
    data = await getJSON<StandingsResponse>("/api/standings");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Puan durumu alınamadı."} />;
  }
  if (data.leagues.length === 0) {
    return (
      <EmptyState title="Puan durumu henüz yok">
        Lig tabloları ESPN&apos;den her güncellemede çekilir. İlk güncelleme tamamlanınca burada görünür.
      </EmptyState>
    );
  }
  return <StandingsBoard leagues={data.leagues} />;
}

export default function StandingsPage() {
  return (
    <>
      <PageHeader kicker="Resmi lig tabloları · ESPN" title="Puan durumu" />
      <Suspense fallback={<SkeletonRows n={12} h={40} />}>
        <Standings />
      </Suspense>
    </>
  );
}
