import { odd, pct, signedPct } from "@/lib/format";
import type { Outcome1X2, SimilarExample, SimilarOddsData } from "@/lib/similar-types";
import { EmptyState, ProbBar, SectionTitle, Stat } from "../ui";

const KEYS: Outcome1X2[] = ["1", "0", "2"];
const KEY_LABEL: Record<Outcome1X2, string> = { "1": "1", "0": "X", "2": "2" };
const KEY_COLOR: Record<Outcome1X2, string> = { "1": "var(--home)", "0": "var(--draw)", "2": "var(--away)" };

/** "2026-10-12" -> "12.10.2026" (saat dilimi dönüşümü yok: tarih zaten maç günü) */
function shortDate(d: string): string {
  const [y, m, day] = d.split("-");
  return `${day}.${m}.${y}`;
}

function resultKey(hg: number, ag: number): Outcome1X2 {
  return hg > ag ? "1" : hg === ag ? "0" : "2";
}

function OddsTriple({ e }: { e: SimilarExample }) {
  return (
    <span className="num whitespace-nowrap">
      {odd(e.odds["1"])} · {odd(e.odds["0"])} · {odd(e.odds["2"])}
    </span>
  );
}

function ExamplesTable({ rows, caption }: { rows: SimilarExample[]; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full table-fixed text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-left text-[0.7rem] uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="w-[5.5rem] px-2 py-1.5 font-medium">Tarih</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Maç</th>
            <th scope="col" className="hidden w-[9.5rem] px-2 py-1.5 font-medium sm:table-cell">1 · X · 2</th>
            <th scope="col" className="w-[3.25rem] px-2 py-1.5 text-right font-medium">Benz.</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const r = resultKey(e.hg, e.ag);
            return (
              <tr key={`${e.source}-${e.date}-${e.home}-${e.away}`} className="border-t border-line align-top">
                <td className="num px-2 py-1.5 text-xs text-muted">{shortDate(e.date)}</td>
                <td className="min-w-0 px-2 py-1.5">
                  <p className="flex min-w-0 items-center gap-1.5">
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-[2px]"
                      style={{ background: KEY_COLOR[r] }}
                      title={`Sonuç: ${KEY_LABEL[r]}`}
                      aria-hidden
                    />
                    <span className="truncate">
                      {e.home} <b className="num">{e.hg}-{e.ag}</b> {e.away}
                    </span>
                  </p>
                  <p className="truncate text-[0.7rem] text-muted">
                    {e.league_name}
                    {e.country ? ` · ${e.country}` : ""}
                    {e.hthg != null && e.htag != null ? ` · İY ${e.hthg}-${e.htag}` : ""}
                    {e.source === "iddaa" ? " · iddaa arşivi" : ""}
                  </p>
                  <p className="text-[0.7rem] text-ink-2 sm:hidden">
                    <OddsTriple e={e} />
                  </p>
                </td>
                <td className="hidden px-2 py-1.5 text-xs text-ink-2 sm:table-cell">
                  <OddsTriple e={e} />
                </td>
                <td className="num px-2 py-1.5 text-right text-xs">{pct(e.similarity)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function SimilarOdds({ data }: { data: SimilarOddsData | null }) {
  if (!data) {
    return (
      <EmptyState title="Benzer oran yok">
        Bu maç için iddaa MS oranı ya da model olasılığı bulunmadığından benzer oranlı geçmiş maçlar aranamadı.
      </EmptyState>
    );
  }
  const { target } = data;
  const thr = pct(data.similarity.min);
  const targetText =
    target.basis === "iddaa" && target.odds
      ? `iddaa MS ${odd(target.odds["1"])} · ${odd(target.odds["0"])} · ${odd(target.odds["2"])}`
      : `model adil oranı ${odd(target.fair_odds["1"])} · ${odd(target.fair_odds["0"])} · ${odd(target.fair_odds["2"])}`;

  if (data.n === 0 || !data.outcomes) {
    return (
      <EmptyState title={data.pool_size === 0 ? "Oran arşivi henüz yüklenmedi" : "Benzer oranlı maç bulunamadı"}>
        {data.pool_size === 0
          ? "Geçmiş maç oranları havuzu boş; arşiv güncellemesi çalıştıktan sonra burada benzer oranlı maçların sonuçları görünecek."
          : `${targetText} için ${data.pool_size.toLocaleString("tr-TR")} geçmiş maç içinde ${thr}+ benzerlikte maç yok (genellikle çok uç oranlarda olur).`}
      </EmptyState>
    );
  }

  const outcomes = data.outcomes;
  const market = target.probs;
  const lgText = data.leagues.map((l) => `${l.name} ${l.count}`).join(" · ");

  return (
    <section className="panel rise flex flex-col gap-5 p-5" aria-label="Benzer oranlı geçmiş maçlar">
      <div>
        <SectionTitle right={<span className="kicker">{thr}+ benzerlik</span>}>Benzer oranlar</SectionTitle>
        <p className="text-sm text-ink-2">
          <span className="num">{targetText}</span> — bu orana çok yakın oranla oynanmış{" "}
          <b className="num text-ink">{data.n.toLocaleString("tr-TR")}</b> geçmiş maç nasıl bitti?
        </p>
        <p className="mt-1 text-[0.7rem] text-muted">{data.similarity.definition}</p>
      </div>

      {data.low_sample && (
        <div className="rounded-lg border border-warn/40 px-3 py-2 text-sm text-warn" role="note">
          <span aria-hidden>▲ </span>
          Düşük örneklem: yalnızca <b className="num">{data.n}</b> maç (en az {data.min_sample} önerilir). Dağılım tesadüfe çok açık; karar
          için tek başına kullanma.
        </div>
      )}

      <div className="flex flex-col gap-3">
        <div>
          <p className="mb-1 text-xs text-muted">
            Gerçekleşen sonuçlar <span className="num">({data.n} maç)</span>
          </p>
          <ProbBar ms={outcomes} height={10} />
        </div>
        <div>
          <p className="mb-1 text-xs text-muted">Piyasa beklentisi (bu oranın marjsız olasılığı)</p>
          <ProbBar ms={market} height={6} />
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          {KEYS.map((k) => {
            const diff = outcomes[k] - market[k];
            const ci = data.outcomes_ci95?.[k];
            return (
              <div key={k} className="rounded-lg bg-surface-2 px-2 py-2">
                <p className="text-xs text-muted">{KEY_LABEL[k]}</p>
                <p className="num text-sm">
                  <b>{pct(outcomes[k])}</b> <span className="text-muted">/ {pct(market[k])}</span>
                </p>
                <p className={`num text-[0.7rem] ${Math.abs(diff) < 0.02 ? "text-muted" : diff > 0 ? "text-good-ink" : "text-critical-ink"}`}>
                  {Math.abs(diff) < 0.02 ? "■" : diff > 0 ? "▲" : "▼"} {signedPct(diff)} puan
                </p>
                {ci && (
                  <p className="num text-[0.65rem] text-muted" title="%95 güven aralığı (Wilson)">
                    {pct(ci[0])}–{pct(ci[1])}
                  </p>
                )}
              </div>
            );
          })}
        </div>
        <p className="text-[0.7rem] text-muted">
          Gerçekleşen / piyasa. Fark güven aralığı içindeyse anlamlı değildir: piyasa bu oran bandında genellikle isabetlidir.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Stat label="Üst 2.5" value={<span className="num">{pct(data.over25)}</span>} />
        <Stat label="KG Var" value={<span className="num">{pct(data.btts)}</span>} />
        <Stat label="Ort. gol" value={<span className="num">{data.avg_goals != null ? data.avg_goals.toFixed(2) : "–"}</span>} />
      </div>

      {data.top_scores.length > 0 && (
        <div>
          <p className="kicker mb-2">En sık skorlar</p>
          <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
            {data.top_scores.map((s) => (
              <div key={s.score} className="rounded-lg border border-line px-2 py-1.5 text-center">
                <p className="num text-base font-semibold">{s.score}</p>
                <p className="num text-[0.7rem] text-muted">
                  {pct(s.share)} · {s.count}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.ht && (
        <div>
          <p className="mb-1 text-xs text-muted">
            İlk yarı sonucu <span className="num">({data.ht.n} maç)</span>
          </p>
          <ProbBar ms={data.ht.outcomes} height={6} />
        </div>
      )}

      {data.closest.length > 0 && (
        <div>
          <p className="kicker mb-2">En yakın oranlı maçlar</p>
          <ExamplesTable rows={data.closest} caption="En yakın oranlı geçmiş maçlar" />
        </div>
      )}

      {data.recent.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer select-none text-sm text-ink-2 hover:text-ink">
            Son oynanan benzer maçlar <span className="num text-muted">({data.recent.length})</span>
          </summary>
          <div className="mt-2">
            <ExamplesTable rows={data.recent} caption="Son oynanan benzer oranlı maçlar" />
          </div>
        </details>
      )}

      <p className="text-[0.7rem] text-muted">
        Kaynak: football-data.co.uk <span className="num">{data.sources["football-data"]}</span> · iddaa arşivi{" "}
        <span className="num">{data.sources.iddaa}</span>
        {data.date_range ? (
          <>
            {" "}
            · <span className="num">{shortDate(data.date_range.from)}–{shortDate(data.date_range.to)}</span>
          </>
        ) : null}
        {lgText ? ` · ${lgText}` : ""}. Oranlar çoğunlukla kapanış oranıdır (pazar ortalaması ya da Pinnacle), marjı arındırılarak karşılaştırılır.
      </p>
    </section>
  );
}
