import { odd, pct } from "@/lib/format";
import type { AltUst, CardModel, CornerModel, IddaaMarket, MatchDetail, ThreeWay } from "@/lib/types";
import { SectionTitle } from "../ui";

/** iddaa'da bu pazar (anahtar + çizgi) varsa sonuç adına göre oran ve marjsız piyasa olasılığı */
function marketOf(d: MatchDetail, key: string, line: string | null): IddaaMarket | undefined {
  return d.iddaa?.markets.find((m) => m.key === key && (line == null || (m.line != null && Number(m.line) === Number(line))));
}

function outcomeOf(m: IddaaMarket | undefined, name: string) {
  return m?.outcomes.find((o) => o.name === name);
}

function ValidityTag({ ok }: { ok: boolean | undefined }) {
  return ok ? (
    <span className="kicker text-good-ink">✓ backtest&apos;te doğrulandı</span>
  ) : (
    <span className="kicker text-warn">deneysel · doğrulanmadı</span>
  );
}

function Compare({ p, m, name }: { p: number; m: IddaaMarket | undefined; name: string }) {
  const o = outcomeOf(m, name);
  if (!o) return <span className="text-muted">–</span>;
  const diff = p - o.p_market;
  return (
    <span className="num" title={`iddaa ${odd(o.odd)} · piyasa (marjsız) ${pct(o.p_market, 1)}`}>
      {odd(o.odd)} <span className="text-muted">({pct(o.p_market)})</span>{" "}
      <span className={diff >= 0 ? "text-good-ink" : "text-critical-ink"}>{diff >= 0 ? "▲" : "▼"}</span>
    </span>
  );
}

function LinesTable({ d, title, rows, mkey }: { d: MatchDetail; title: string; rows: Record<string, AltUst>; mkey: string }) {
  const lines = Object.keys(rows).sort((a, b) => Number(a) - Number(b));
  if (lines.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[300px] text-xs">
        <thead className="text-muted">
          <tr>
            <th className="py-1 text-left font-medium">{title}</th>
            <th className="px-1 py-1 text-right font-medium">Alt</th>
            <th className="px-1 py-1 text-right font-medium">Üst</th>
            <th className="py-1 text-right font-medium" title="iddaa oranı (piyasa olasılığı); ▲ model daha emin">iddaa Alt</th>
            <th className="py-1 text-right font-medium">iddaa Üst</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/60">
          {lines.map((L) => {
            const m = marketOf(d, mkey, L);
            return (
              <tr key={L}>
                <td className="num py-1">{L}</td>
                <td className="num px-1 py-1 text-right">{pct(rows[L].Alt)}</td>
                <td className="num px-1 py-1 text-right font-semibold">{pct(rows[L]["Üst"])}</td>
                <td className="py-1 text-right"><Compare p={rows[L].Alt} m={m} name="Alt" /></td>
                <td className="py-1 text-right"><Compare p={rows[L]["Üst"]} m={m} name="Üst" /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ThreeWayRow({ d, title, p, mkey }: { d: MatchDetail; title: string; p: ThreeWay; mkey: string }) {
  const m = marketOf(d, mkey, null);
  const names = [
    { k: "1" as const, label: d.match.home.short_name ?? d.match.home.name },
    { k: "0" as const, label: "Eşit" },
    { k: "2" as const, label: d.match.away.short_name ?? d.match.away.name },
  ];
  return (
    <div>
      <p className="mb-1 text-xs font-semibold">{title}</p>
      <div className="grid grid-cols-3 gap-1.5 text-center">
        {names.map((n) => (
          <div key={n.k} className="rounded-md bg-surface-2 px-1.5 py-1.5">
            <p className="truncate text-[0.68rem] text-muted" title={n.label}>{n.label}</p>
            <p className="num text-sm font-semibold">{pct(p[n.k])}</p>
            <p className="text-[0.68rem]"><Compare p={p[n.k]} m={m} name={n.k} /></p>
          </div>
        ))}
      </div>
    </div>
  );
}

function CornerBlock({ d, c }: { d: MatchDetail; c: CornerModel }) {
  const ok = d.model?.family_validation?.korner;
  const ranges = c.ranges ? Object.entries(c.ranges) : [];
  const rangeMkt = marketOf(d, "korner_ar", null);
  const hnd = c.handicap ? Object.entries(c.handicap).sort((a, b) => Number(a[0]) - Number(b[0])) : [];
  return (
    <div className="panel flex flex-col gap-4 p-5">
      <SectionTitle right={<ValidityTag ok={ok} />}>Korner</SectionTitle>
      <p className="text-sm text-ink-2">
        Beklenen korner: <b className="num text-ink">{c.mu_home.toFixed(1)}</b> – <b className="num text-ink">{c.mu_away.toFixed(1)}</b>{" "}
        (toplam <span className="num">{(c.mu_home + c.mu_away).toFixed(1)}</span>)
      </p>
      <LinesTable d={d} title="Toplam" rows={c.lines} mkey="korner_au" />
      {c.home_lines && <LinesTable d={d} title={`${d.match.home.short_name ?? d.match.home.name}`} rows={c.home_lines} mkey="ev_korner_au" />}
      {c.away_lines && <LinesTable d={d} title={`${d.match.away.short_name ?? d.match.away.name}`} rows={c.away_lines} mkey="dep_korner_au" />}
      {c.kdc && <ThreeWayRow d={d} title="Kim daha çok korner kullanır" p={c.kdc} mkey="korner_kdc" />}
      {ranges.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold">Toplam korner aralığı</p>
          <div className="grid grid-cols-3 gap-1.5 text-center">
            {ranges.map(([name, p]) => (
              <div key={name} className="rounded-md bg-surface-2 px-1.5 py-1.5">
                <p className="text-[0.68rem] text-muted">{name}</p>
                <p className="num text-sm font-semibold">{pct(p)}</p>
                <p className="text-[0.68rem]"><Compare p={p} m={rangeMkt} name={name} /></p>
              </div>
            ))}
          </div>
        </div>
      )}
      {hnd.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold">Korner handikabı (ev sahibine eklenir)</p>
          <div className="flex flex-wrap gap-1.5 text-xs">
            {hnd.map(([L, v]) => (
              <span key={L} className="num rounded border border-line px-2 py-1" title="1: ev sahibi handikapla önde · 2: deplasman">
                {Number(L) > 0 ? `+${L}` : L}: 1 <b>{pct(v["1"])}</b> · 2 <b>{pct(v["2"])}</b>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CardBlock({ d, c }: { d: MatchDetail; c: CardModel }) {
  const ok = d.model?.family_validation?.kart;
  const red = marketOf(d, "kirmizi", null);
  return (
    <div className="panel flex flex-col gap-4 p-5">
      <SectionTitle right={<ValidityTag ok={ok} />}>Kart</SectionTitle>
      <p className="text-sm text-ink-2">
        Beklenen kart puanı: <b className="num text-ink">{c.mu_home.toFixed(1)}</b> – <b className="num text-ink">{c.mu_away.toFixed(1)}</b>{" "}
        (toplam <span className="num">{(c.mu_home + c.mu_away).toFixed(1)}</span>)
      </p>
      <LinesTable d={d} title="Toplam" rows={c.lines} mkey="kart_au" />
      {Object.keys(c.ht_lines).length > 0 && <LinesTable d={d} title="İlk yarı" rows={c.ht_lines} mkey="iy_kart_au" />}
      <ThreeWayRow d={d} title="Kim daha çok kart görür" p={c.kdc} mkey="kart_kdc" />
      {c.p_red != null && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-xs font-semibold">Kırmızı kart olur mu</span>
          <span className="num">
            Evet <b>{pct(c.p_red, 1)}</b> · Hayır <b>{pct(1 - c.p_red, 1)}</b>
          </span>
          <span className="text-xs">
            iddaa Evet: <Compare p={c.p_red} m={red} name="Evet" />
          </span>
        </div>
      )}
      <p className="text-[0.7rem] leading-relaxed text-muted">
        iddaa sayımı: sarı kart 1, kırmızı kart 2 (ikinci sarıyla atılan oyuncu 1 + 2), 90 dakika. Hakem verisi yok: model
        takımların ve ligin kart eğilimine dayanır.
      </p>
    </div>
  );
}

export default function CornerCardPanel({ d }: { d: MatchDetail }) {
  if (!d.corners && !d.cards) return null;
  return (
    <section className="rise" style={{ animationDelay: "180ms" }}>
      <SectionTitle right={<span className="kicker">model · iddaa oranı (marjsız piyasa olasılığı)</span>}>Korner ve kart</SectionTitle>
      <div className="grid gap-6 lg:grid-cols-2">
        {d.corners && <CornerBlock d={d} c={d.corners} />}
        {d.cards && <CardBlock d={d} c={d.cards} />}
      </div>
    </section>
  );
}
