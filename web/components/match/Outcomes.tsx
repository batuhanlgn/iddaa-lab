import { fairOdd, pct } from "@/lib/format";
import type { MatchDetail, StandardMarket } from "@/lib/types";

function find(markets: StandardMarket[], key: string, line: string | null = null): StandardMarket | undefined {
  return markets.find((m) => m.key === key && m.line === line);
}

function p(m: StandardMarket | undefined, name: string): number {
  return m?.outcomes.find((o) => o.name === name)?.p_model ?? 0;
}

export default function Outcomes({ d }: { d: MatchDetail }) {
  const markets = d.markets ?? [];
  const ms = find(markets, "ms");
  const big = [
    { name: "1", label: d.match.home.name, color: "var(--home)" },
    { name: "0", label: "Beraberlik", color: "var(--draw)" },
    { name: "2", label: d.match.away.name, color: "var(--away)" },
  ];
  const lines = ["1.5", "2.5", "3.5"];
  const kg = find(markets, "kg");
  const iy = find(markets, "iy");
  const evAu = ["0.5", "1.5"].map((l) => ({ l, home: p(find(markets, "ev_au", l), "Üst"), away: p(find(markets, "dep_au", l), "Üst") }));

  return (
    <div className="flex flex-col gap-6">
      {/* 1X2 — yatay çubuklar, değer uçta */}
      <div className="flex flex-col gap-3">
        {big.map((b) => {
          const v = p(ms, b.name);
          return (
            <div key={b.name} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
              <span className="truncate text-sm text-ink-2">{b.label}</span>
              <div className="h-6 rounded-r-[4px]" style={{ width: `${Math.max(v * 100, 1)}%`, background: b.color }} />
              <span className="num w-24 text-right text-sm">
                <b className="text-base text-ink">{pct(v, 1)}</b> <span className="text-muted">({fairOdd(v)})</span>
              </span>
            </div>
          );
        })}
        <p className="text-xs text-muted">Parantez içi: model adil oranı (1 / olasılık, marjsız).</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <MiniTable
          title="Toplam gol"
          head={["Çizgi", "Alt", "Üst"]}
          rows={lines.map((l) => {
            const m = find(markets, "au", l);
            return [l, pct(p(m, "Alt")), pct(p(m, "Üst"))];
          })}
        />
        <MiniTable
          title="Takım golleri (Üst)"
          head={["Çizgi", d.match.home.short_name ?? "Ev", d.match.away.short_name ?? "Dep"]}
          rows={evAu.map((r) => [r.l, pct(r.home), pct(r.away)])}
        />
        <MiniTable
          title="Karşılıklı gol · çifte şans"
          head={["Pazar", "Olasılık", "Adil"]}
          rows={[
            ["KG Var", pct(p(kg, "Var")), fairOdd(p(kg, "Var"))],
            ["KG Yok", pct(p(kg, "Yok")), fairOdd(p(kg, "Yok"))],
            ["1-X", pct(p(find(markets, "cs"), "1 ve 0")), fairOdd(p(find(markets, "cs"), "1 ve 0"))],
            ["X-2", pct(p(find(markets, "cs"), "0 ve 2")), fairOdd(p(find(markets, "cs"), "0 ve 2"))],
            ["1-2", pct(p(find(markets, "cs"), "1 ve 2")), fairOdd(p(find(markets, "cs"), "1 ve 2"))],
          ]}
        />
        <MiniTable
          title={`İlk yarı${d.model?.family_validation?.iy ? "" : " · doğrulanmadı"}`}
          head={["Sonuç", "Olasılık", "Adil"]}
          rows={[
            ["İY 1", pct(p(iy, "1")), fairOdd(p(iy, "1"))],
            ["İY X", pct(p(iy, "0")), fairOdd(p(iy, "0"))],
            ["İY 2", pct(p(iy, "2")), fairOdd(p(iy, "2"))],
            ["İY 0.5 Üst", pct(p(find(markets, "iy_au", "0.5"), "Üst")), fairOdd(p(find(markets, "iy_au", "0.5"), "Üst"))],
          ]}
        />
      </div>
    </div>
  );
}

function MiniTable({ title, head, rows }: { title: string; head: string[]; rows: string[][] }) {
  return (
    <div className="rounded-lg border border-line">
      <p className="border-b border-line px-3 py-2 text-xs font-semibold uppercase tracking-wider text-ink-2">{title}</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted">
            {head.map((h, i) => (
              <th key={h} className={`px-3 py-1.5 font-medium ${i ? "text-right" : "text-left"}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r[0]} className="border-t border-line/60">
              {r.map((c, i) => (
                <td key={i} className={`px-3 py-1.5 ${i ? "num text-right" : "text-ink-2"}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
