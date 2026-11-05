import Link from "next/link";
import { Suspense } from "react";
import ErrorPanel from "@/components/ErrorPanel";
import { ConfidenceBadge, EmptyState, PageHeader, SectionTitle, SkeletonRows } from "@/components/ui";
import { dateTime, odd, pct, relative, signedPct } from "@/lib/format";
import { BackendError, getJSON } from "@/lib/server-api";
import type { SurpriseResponse, SurpriseRow } from "@/lib/types";

function evClass(ev: number | null): string {
  if (ev === null) return "text-muted";
  return ev >= 0 ? "text-good-ink" : ev > -0.15 ? "text-ink-2" : "text-critical-ink";
}

function SelectionLabel({ s }: { s: string }) {
  const title =
    s === "1/2"
      ? "İlk yarıyı ev sahibi önde kapatır, maçı deplasman kazanır"
      : s === "2/1"
        ? "İlk yarıyı deplasman önde kapatır, maçı ev sahibi kazanır"
        : undefined;
  return (
    <span className="num rounded border border-line px-1.5 py-0.5 text-xs font-semibold" title={title}>
      {s}
    </span>
  );
}

function CandidateTable({ rows, empty }: { rows: SurpriseRow[]; empty: string }) {
  if (rows.length === 0) return <p className="px-4 py-6 text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-line">
            <th className="px-3 py-2 font-medium">Maç</th>
            <th className="px-2 py-2 font-medium">Seçim</th>
            <th className="px-2 py-2 text-right font-medium">Oran</th>
            <th className="px-2 py-2 text-right font-medium" title="Modelin olasılığı">Model</th>
            <th className="px-2 py-2 text-right font-medium" title="1 / model olasılığı">Adil oran</th>
            <th className="px-3 py-2 text-right font-medium" title="Model olasılığı × oran − 1">Beklenen getiri</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.match_id}-${r.selection}`} className="border-b border-line/60 last:border-0">
              <td className="px-3 py-1.5">
                <Link href={`/mac/${r.match_id}`} className="block truncate font-medium hover:underline">
                  {r.home} – {r.away}
                </Link>
                <span className="flex flex-wrap items-center gap-x-2 text-[0.7rem] text-muted">
                  {dateTime(r.date_utc)} · {r.country} {r.league_name} · beklenen gol{" "}
                  <span className="num">{r.goals_expected.toFixed(1)}</span>
                  {r.confidence !== "yüksek" && <ConfidenceBadge level={r.confidence} />}
                </span>
              </td>
              <td className="px-2 py-1.5">
                <SelectionLabel s={r.selection} />
              </td>
              <td className="num px-2 py-1.5 text-right font-semibold">{r.odd ? odd(r.odd) : <span className="text-muted">yok</span>}</td>
              <td className="num px-2 py-1.5 text-right">{pct(r.p_model, 1)}</td>
              <td className="num px-2 py-1.5 text-right text-ink-2">{r.fair_odd ? r.fair_odd.toFixed(1) : "–"}</td>
              <td className={`num px-3 py-1.5 text-right ${evClass(r.ev_model)}`}>{r.ev_model === null ? "–" : signedPct(r.ev_model, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Block({
  title,
  kicker,
  value,
  prob,
  valueEmpty,
  probEmpty,
}: {
  title: string;
  kicker: string;
  value: SurpriseRow[];
  prob: SurpriseRow[];
  valueEmpty: string;
  probEmpty: string;
}) {
  return (
    <section className="rise flex flex-col gap-4">
      <SectionTitle right={<span className="kicker">{kicker}</span>}>{title}</SectionTitle>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="panel">
          <p className="kicker px-3 pt-3">Değere göre — oran, modelin beklediğinden en cömert olanlar</p>
          <CandidateTable rows={value} empty={valueEmpty} />
        </div>
        <div className="panel">
          <p className="kicker px-3 pt-3">Olasılığa göre — en sık tutacak olanlar</p>
          <CandidateTable rows={prob} empty={probEmpty} />
        </div>
      </div>
    </section>
  );
}

async function Surprise() {
  let d: SurpriseResponse;
  try {
    d = await getJSON<SurpriseResponse>("/api/surprise");
  } catch (e) {
    if (e instanceof BackendError && e.status === 404) {
      return <EmptyState title="Henüz liste yok">Sürpriz adayları bir sonraki güncellemeyle yayınlanacak.</EmptyState>;
    }
    return <ErrorPanel message={e instanceof BackendError ? e.message : "Sürpriz adayları alınamadı."} />;
  }
  const margin = d.reversal.median_margin;
  return (
    <div className="flex flex-col gap-10">
      <div className="rounded-lg border border-warn/50 bg-warn/10 px-4 py-3 text-sm text-ink-2" role="note">
        <p className="font-semibold text-warn">⚠ Bunlar piyango biletidir, kazanç yolu değil.</p>
        <ul className="mt-1 list-disc pl-5">
          <li>
            İY/MS dönüşü maçların yalnızca ~%3-5&apos;inde olur; iddaa bu pazarda{" "}
            {margin !== null ? <span className="num">%{(margin * 100).toFixed(0)}</span> : "yüksek"} marj keser. 5.5 Üst&apos;te
            marj ~%17&apos;dir.
          </li>
          <li>
            &quot;Değere göre&quot; listesinin başı bile en iyi ihtimalle başa baştır; arada uzun kayıp serileri olur. Tutarlar küçük
            ve eşit tutulmalı.
          </li>
          <li>Kombine yapma: iki dönüşü birleştirmek oranı katlar ama tutma ihtimali binde 1&apos;in altına düşer, marj iki kez kesilir.</li>
          <li>Oranlar maça kadar değişir; oynamadan önce iddaa&apos;daki güncel oranı kontrol et.</li>
        </ul>
      </div>

      <Block
        title="İY/MS dönüşü"
        kicker={`1/2 · 2/1 · ${d.reversal.n} teklif · ${d.days} gün`}
        value={d.reversal.by_value}
        prob={d.reversal.by_prob}
        valueEmpty="Bültende İY/MS oranı olan maç yok."
        probEmpty="Bültende İY/MS oranı olan maç yok."
      />
      <p className="-mt-6 text-xs text-muted">
        <b>2/1</b>: ilk yarıyı deplasman önde kapatır, maçı ev sahibi kazanır. <b>1/2</b>: ilk yarıyı ev sahibi önde kapatır, maçı
        deplasman kazanır. Model bunu gollerin iki yarıya dağılımından hesaplar (backtest&apos;te doğrulandı).
      </p>

      <Block
        title="5.5 Üst"
        kicker={`6+ gol · ${d.over55.n_offered}/${d.over55.n} maçta iddaa oranı`}
        value={d.over55.by_value}
        prob={d.over55.by_prob}
        valueEmpty="iddaa şu an hiçbir maçta 5.5 Üst sunmuyor (oranlar maç detayından, maça yaklaştıkça gelir)."
        probEmpty="Model kapsamında maç yok."
      />
      <p className="-mt-6 text-xs text-muted">
        5.5 Üst oranı iddaa&apos;nın maç detayından alınır; iddaa bu çizgide &quot;Alt&quot;ı genelde kapattığı için piyasa olasılığı
        marjlı (1/oran) gösterilir. Oranı olmayan maçlarda yalnız model olasılığı vardır.
      </p>

      <p className="text-xs text-muted">Güncellendi {relative(d.generated_at)}.</p>
    </div>
  );
}

export default function SurprisePage() {
  return (
    <>
      <PageHeader kicker="Yüksek oran · nadir sonuç" title="Sürpriz adayları" />
      <Suspense fallback={<SkeletonRows n={8} h={44} />}>
        <Surprise />
      </Suspense>
    </>
  );
}
