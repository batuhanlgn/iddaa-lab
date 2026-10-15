import { dateTime, odd, pct } from "@/lib/format";
import type { FormMatch, MatchDetail } from "@/lib/types";
import { SectionTitle } from "../ui";

function result(f: FormMatch): "G" | "B" | "M" {
  const gf = f.is_home ? f.home_goals : f.away_goals;
  const ga = f.is_home ? f.away_goals : f.home_goals;
  return gf > ga ? "G" : gf === ga ? "B" : "M";
}

const RES_STYLE = {
  G: "border-good/50 text-good-ink",
  B: "border-line-strong text-ink-2",
  M: "border-critical/50 text-critical-ink",
} as const;

export default function SideInfo({ d }: { d: MatchDetail }) {
  const hist = d.odds_history_ms;
  const byNo = (no: number) => hist.filter((h) => h.outcome_no === no);
  const moves = [1, 2, 3].map((no) => {
    const xs = byNo(no);
    return { no, first: xs[0]?.odd, last: xs[xs.length - 1]?.odd, n: xs.length };
  });
  return (
    <section className="panel rise flex flex-col gap-5 p-5">
      <div>
        <SectionTitle>Son form</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          {(["home", "away"] as const).map((s) => (
            <div key={s}>
              <p className="mb-2 text-sm font-semibold">{d.match[s].name}</p>
              {d.form[s].length === 0 ? (
                <p className="text-sm text-muted">Geçmiş maç yok.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {d.form[s].map((f) => {
                    const r = result(f);
                    return (
                      <li key={f.id} className="flex items-center gap-2">
                        <span className={`num grid h-5 w-5 place-items-center rounded border text-[0.65rem] font-semibold ${RES_STYLE[r]}`}>{r}</span>
                        <span className="num w-14 text-xs text-muted">{dateTime(f.date_utc).split(" ").slice(0, 2).join(" ")}</span>
                        <span className="truncate">
                          {f.hn} <b className="num">{f.home_goals}-{f.away_goals}</b> {f.an}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ))}
        </div>
        <p className="mt-2 text-[0.7rem] text-muted">G: galibiyet · B: beraberlik · M: mağlubiyet</p>
      </div>

      {d.corners && (
        <div>
          <SectionTitle right={<span className="kicker">deneysel</span>}>Korner</SectionTitle>
          <p className="mb-2 text-sm text-ink-2">
            Beklenen korner: <b className="num text-ink">{d.corners.mu_home.toFixed(1)}</b> – <b className="num text-ink">{d.corners.mu_away.toFixed(1)}</b>{" "}
            (toplam <span className="num">{(d.corners.mu_home + d.corners.mu_away).toFixed(1)}</span>)
          </p>
          <div className="flex flex-wrap gap-1.5 text-xs">
            {Object.entries(d.corners.lines).map(([line, v]) => (
              <span key={line} className="num rounded border border-line px-2 py-1">
                {line}: Alt <b>{pct(v.Alt)}</b> · Üst <b>{pct(v["Üst"])}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      {hist.length > 0 && (
        <div>
          <SectionTitle right={<span className="kicker">arşivden</span>}>MS oran hareketi</SectionTitle>
          <div className="grid grid-cols-3 gap-2 text-center">
            {moves.map((m) => {
              const diff = m.first && m.last ? m.last - m.first : 0;
              return (
                <div key={m.no} className="rounded-lg bg-surface-2 px-2 py-2">
                  <p className="text-xs text-muted">{m.no === 1 ? "1" : m.no === 2 ? "X" : "2"}</p>
                  <p className="num text-sm">
                    {odd(m.first)} → <b>{odd(m.last)}</b>
                  </p>
                  <p className={`num text-[0.7rem] ${diff < 0 ? "text-good-ink" : diff > 0 ? "text-critical-ink" : "text-muted"}`}>
                    {diff < 0 ? "▼ düştü" : diff > 0 ? "▲ yükseldi" : "■ sabit"} · {m.n} kayıt
                  </p>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[0.7rem] text-muted">Düşen oran: piyasanın o sonuca güveni artıyor.</p>
        </div>
      )}
    </section>
  );
}
