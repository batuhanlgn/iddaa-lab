import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import CornerCardPanel from "@/components/match/CornerCardPanel";
import IddaaMarkets from "@/components/match/IddaaMarkets";
import LeagueContext from "@/components/match/LeagueContext";
import MatchHeader from "@/components/match/MatchHeader";
import ModelNotes from "@/components/match/ModelNotes";
import Outcomes from "@/components/match/Outcomes";
import ScoreHeatmap from "@/components/match/ScoreHeatmap";
import ScoutReport from "@/components/match/ScoutReport";
import SimilarOdds from "@/components/match/SimilarOdds";
import SimulationPanel from "@/components/match/SimulationPanel";
import SideInfo from "@/components/match/SideInfo";
import { EmptyState, SectionTitle, SkeletonRows } from "@/components/ui";
import { BackendError, getJSON, staticMatchIds } from "@/lib/server-api";
import type { MatchDetail } from "@/lib/types";

// Statik modda tüm kapsam içi maçlar önceden üretilir. Canlı modda tek bir yer tutucu yeterli (sayfalar istek
// anında Suspense içinde üretilir; "0" kimliği notFound döner) — cacheComponents boş liste kabul etmez.
export async function generateStaticParams(): Promise<{ id: string }[]> {
  const ids = staticMatchIds();
  return ids.length ? ids.map((id) => ({ id })) : [{ id: "0" }];
}

async function MatchData({ params }: Pick<PageProps<"/mac/[id]">, "params">) {
  const { id } = await params;
  if (!/^\d{1,20}$/.test(id) || id === "0") notFound();
  let d: MatchDetail;
  try {
    d = await getJSON<MatchDetail>(`/api/matches/${id}`);
  } catch (e) {
    if (e instanceof BackendError && e.status === 404) notFound();
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Maç verisi alınamadı."} />;
  }
  if (!d.covered || !d.model || !d.markets || !d.score_matrix) {
    return (
      <>
        <MatchHeader d={d} />
        <EmptyState title="Model kapsamı dışında">{d.coverage_note ?? "Bu maç için model tahmini üretilemedi."}</EmptyState>
        <div className="mt-6">
          <LeagueContext d={d} />
        </div>
      </>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <MatchHeader d={d} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <section className="panel rise p-5" style={{ animationDelay: "60ms" }}>
          <SectionTitle right={<span className="kicker">Dixon-Coles skor modeli</span>}>Olasılıklar</SectionTitle>
          <Outcomes d={d} />
        </section>
        <section className="panel rise p-5" style={{ animationDelay: "120ms" }}>
          <SectionTitle right={<span className="kicker">ev ↓ · deplasman →</span>}>Skor dağılımı</SectionTitle>
          <ScoreHeatmap d={d} />
        </section>
      </div>

      {d.scout && <ScoutReport scout={d.scout} />}

      <section className="rise" style={{ animationDelay: "160ms" }}>
        <SectionTitle right={<span className="kicker">iddaa oranı · model · piyasa · harman</span>}>iddaa pazarları</SectionTitle>
        {d.iddaa && d.iddaa.markets.length > 0 ? (
          <IddaaMarkets d={d} />
        ) : (
          <EmptyState title="Bültende eşleşme yok">
            Bu maç iddaa bülteninde bulunamadı ya da henüz eşleşmedi. Model olasılıkları yukarıda; adil oran = 1 / olasılık.
          </EmptyState>
        )}
      </section>

      <CornerCardPanel d={d} />

      {d.similar !== undefined && <SimilarOdds data={d.similar} />}

      <section className="rise" style={{ animationDelay: "200ms" }}>
        <SectionTitle right={<span className="kicker">{d.sim ? `${d.sim.n_sims.toLocaleString("tr-TR")} simülasyon` : ""}</span>}>
          Maç simülasyonu
        </SectionTitle>
        {d.sim ? (
          <SimulationPanel d={d} />
        ) : (
          <EmptyState title="Simülasyon yok">Bu maç için şut verisi yetersiz olduğundan oyuncu simülasyonu çalıştırılmadı.</EmptyState>
        )}
      </section>

      <LeagueContext d={d} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SideInfo d={d} />
        <ModelNotes d={d} />
      </div>
    </div>
  );
}

export default function MatchPage({ params }: PageProps<"/mac/[id]">) {
  return (
    <>
      <Link href="/" className="mb-4 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink">
        ← Bülten
      </Link>
      <Suspense
        fallback={
          <div className="flex flex-col gap-4">
            <div className="skeleton h-36 w-full" />
            <SkeletonRows n={4} h={180} />
          </div>
        }
      >
        <MatchData params={params} />
      </Suspense>
    </>
  );
}
