import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import PlayerBoard from "@/components/PlayerBoard";
import { EmptyState, PageHeader, SkeletonRows } from "@/components/ui";
import { BackendError, getJSON } from "@/lib/server-api";
import type { TopPlayersResponse } from "@/lib/types";

async function Players() {
  let data: TopPlayersResponse;
  try {
    data = await getJSON<TopPlayersResponse>("/api/players/top?days=3&limit=300");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Oyuncu projeksiyonları alınamadı."} />;
  }
  if (data.items.length === 0) {
    return (
      <EmptyState title="Oyuncu projeksiyonu yok">
        Önümüzdeki 72 saatte oyuncu düzeyi simülasyonu yapılmış maç yok. Oyuncu verisi, maç özetleri indirildikçe ve model
        güncellendikçe dolar.
      </EmptyState>
    );
  }
  return <PlayerBoard data={data} />;
}

export default function PlayersPage() {
  return (
    <>
      <PageHeader kicker="Önümüzdeki 72 saat · maç simülasyonundan" title="Oyuncu projeksiyonları" />
      <Suspense fallback={<SkeletonRows n={10} h={44} />}>
        <Players />
      </Suspense>
    </>
  );
}
