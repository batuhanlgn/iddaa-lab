import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import JobControls from "@/components/JobControls";
import { PageHeader, SectionTitle, SkeletonRows } from "@/components/ui";
import { compact, dateTime, pct } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { CoverageResponse, StatusResponse } from "@/lib/types";

async function Status() {
  let s: StatusResponse;
  try {
    s = await getJSON<StatusResponse>("/api/status");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Durum alınamadı."} />;
  }
  const c = s.counts;
  return (
    <div className="flex flex-col gap-4">
      <div className="panel grid grid-cols-2 gap-4 p-5 sm:grid-cols-4 lg:grid-cols-8">
        {[
          ["Maç", c.matches],
          ["Biten", c.completed],
          ["Detaylı özet", c.summaries_ok],
          ["Oyuncu-maç", c.player_rows],
          ["Bülten maçı", c.iddaa_events],
          ["Eşleşen", c.iddaa_matched],
          ["Oran kaydı", c.odds_history],
          ["Tahmin", c.predictions],
        ].map(([l, v]) => (
          <div key={l as string}>
            <p className="kicker">{l}</p>
            <p className="text-xl font-semibold">{compact(Number(v ?? 0))}</p>
          </div>
        ))}
      </div>
      <JobControls initial={s} />
    </div>
  );
}

async function Coverage() {
  let d: CoverageResponse;
  try {
    d = await getJSON<CoverageResponse>("/api/coverage");
  } catch (e) {
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Kapsam raporu alınamadı."} />;
  }
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Lig</th>
            <th className="px-2 py-2 text-right font-medium">Maç</th>
            <th className="px-2 py-2 text-right font-medium">Biten</th>
            <th className="px-2 py-2 text-right font-medium" title="Detay penceresindeki maçlarda oyuncu istatistiği olan özet oranı">Oyuncu verisi</th>
            <th className="px-2 py-2 text-right font-medium">Eksik istatistik</th>
            <th className="px-2 py-2 text-right font-medium">Şut / Korner satırı</th>
            <th className="px-2 py-2 text-right font-medium">İY skoru</th>
            <th className="px-2 py-2 text-right font-medium">Yaklaşan</th>
            <th className="px-2 py-2 text-right font-medium">iddaa eşleşmesi</th>
            <th className="px-4 py-2 font-medium">Son biten</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/60">
          {d.leagues.map((l) => {
            const det = l.summaries_ok + l.summaries_missing;
            const ratio = det ? l.summaries_ok / det : 0;
            return (
              <tr key={l.slug} className={l.total === 0 ? "text-muted" : ""}>
                <td className="px-4 py-1.5">
                  <span className="font-medium">{l.name}</span> <span className="text-xs text-muted">{l.country}{l.is_cup ? " · kupa" : ""}</span>
                </td>
                <td className="num px-2 py-1.5 text-right">{l.total.toLocaleString("tr-TR")}</td>
                <td className="num px-2 py-1.5 text-right">{l.completed.toLocaleString("tr-TR")}</td>
                <td className={`num px-2 py-1.5 text-right ${det && ratio < 0.8 ? "text-warn" : ""}`}>
                  {l.summaries_ok.toLocaleString("tr-TR")} {det ? <span className="text-xs text-muted">({pct(ratio)})</span> : null}
                </td>
                <td className="num px-2 py-1.5 text-right text-ink-2">{l.summaries_missing}</td>
                <td className="num px-2 py-1.5 text-right text-ink-2">
                  {l.shots_rows} / {l.corners_rows}
                </td>
                <td className="num px-2 py-1.5 text-right text-ink-2">{l.with_ht}</td>
                <td className="num px-2 py-1.5 text-right">{l.upcoming}</td>
                <td className="num px-2 py-1.5 text-right">{l.iddaa_linked}</td>
                <td className="num px-4 py-1.5 text-xs text-ink-2">{dateTime(l.last_completed)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function DataPage() {
  return (
    <>
      <PageHeader kicker="ESPN + iddaa · ücretsiz kaynaklar" title="Veri durumu" />
      <div className="flex flex-col gap-10">
        <section>
          <SectionTitle>İşler</SectionTitle>
          <Suspense fallback={<SkeletonRows n={2} h={90} />}>
            <Status />
          </Suspense>
        </section>
        <section>
          <SectionTitle right={<span className="kicker">lig × veri alanı</span>}>Kapsam raporu</SectionTitle>
          <Suspense fallback={<SkeletonRows n={10} h={32} />}>
            <Coverage />
          </Suspense>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Skor modeli tüm biten maçları kullanır (27 ay). Oyuncu/şut detayı ana liglerde 16, genişletilmiş liglerde 8 ay
            geriye çekilir. &quot;Eksik istatistik&quot;: kaynağın tüm değerleri 0 döndürdüğü maçlar — sıfır sayılmaz, modelden
            çıkarılır.
          </p>
        </section>
      </div>
    </>
  );
}
