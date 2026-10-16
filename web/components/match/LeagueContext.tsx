import { dateTime } from "@/lib/format";
import type { H2HMatch, MatchDetail } from "@/lib/types";
import StandingsTable from "../StandingsTable";
import { SectionTitle } from "../ui";

type Res = "G" | "B" | "M";

/** Sonuç bu maçın EV SAHİBİ açısından (uzatma dahil nihai skor). */
function resultFor(teamId: string, h: H2HMatch): Res {
  const gf = h.home_id === teamId ? h.home_goals : h.away_goals;
  const ga = h.home_id === teamId ? h.away_goals : h.home_goals;
  return gf > ga ? "G" : gf === ga ? "B" : "M";
}

const RES_STYLE: Record<Res, string> = {
  G: "border-good/50 text-good-ink",
  B: "border-line-strong text-ink-2",
  M: "border-critical/50 text-critical-ink",
};

function HeadToHead({ d }: { d: MatchDetail }) {
  const list = d.h2h ?? [];
  const home = d.match.home;
  const away = d.match.away;
  if (list.length === 0) {
    return <p className="text-sm text-muted">Son yıllarda iki takım arasında resmi maç bulunamadı.</p>;
  }
  const tally = { G: 0, B: 0, M: 0 };
  let gf = 0;
  let ga = 0;
  list.forEach((h) => {
    tally[resultFor(home.id, h)] += 1;
    gf += h.home_id === home.id ? h.home_goals : h.away_goals;
    ga += h.home_id === home.id ? h.away_goals : h.home_goals;
  });
  return (
    <div>
      <div className="mb-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-surface-2 px-2 py-2">
          <p className="truncate text-xs text-muted">{home.name}</p>
          <p className="num text-lg font-semibold">{tally.G}</p>
        </div>
        <div className="rounded-lg bg-surface-2 px-2 py-2">
          <p className="text-xs text-muted">Beraberlik</p>
          <p className="num text-lg font-semibold">{tally.B}</p>
        </div>
        <div className="rounded-lg bg-surface-2 px-2 py-2">
          <p className="truncate text-xs text-muted">{away.name}</p>
          <p className="num text-lg font-semibold">{tally.M}</p>
        </div>
      </div>
      <ul className="flex flex-col gap-1.5 text-sm">
        {list.map((h) => {
          const r = resultFor(home.id, h);
          return (
            <li key={h.id} className="flex items-center gap-2">
              <span className={`num grid h-5 w-5 shrink-0 place-items-center rounded border text-[0.65rem] font-semibold ${RES_STYLE[r]}`}>
                {r}
              </span>
              <span className="num w-20 shrink-0 text-xs text-muted">{dateTime(h.date_utc).split(" ").slice(0, 3).join(" ")}</span>
              <span className="min-w-0 flex-1 truncate">
                {h.home_name} <b className="num">{h.home_goals}-{h.away_goals}</b> {h.away_name}
                {h.extra_time && <span className="ml-1 text-xs text-muted">(uzt.)</span>}
              </span>
              <span className="hidden max-w-[9rem] shrink-0 truncate text-xs text-muted sm:inline">{h.league_name}</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[0.7rem] text-muted">
        G/B/M {home.name} açısından · toplam gol <span className="num">{gf}-{ga}</span> · uzatma dahil nihai skor
      </p>
    </div>
  );
}

export default function LeagueContext({ d }: { d: MatchDetail }) {
  const st = d.standings ?? null;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="panel rise p-5">
        <SectionTitle right={<span className="kicker">son {d.h2h?.length ?? 0} maç</span>}>Karşılıklı geçmiş</SectionTitle>
        <HeadToHead d={d} />
      </section>
      <section className="panel rise p-5">
        <SectionTitle right={<span className="kicker">{st ? st.group : d.match.league_name}</span>}>Puan durumu</SectionTitle>
        {st ? (
          <StandingsTable entries={st.entries} highlight={[d.match.home.id, d.match.away.id]} compact />
        ) : (
          <p className="text-sm text-muted">Bu organizasyon için lig tablosu yok (eleme usulü kupa) ya da henüz çekilmedi.</p>
        )}
      </section>
    </div>
  );
}
