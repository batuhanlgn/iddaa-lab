import type { StandingEntry } from "@/lib/types";
import { Crest } from "./ui";

// ESPN bölge notları (tablo henüz kesinleşmediği için "Relegated" = küme düşme hattı)
const NOTE_TR: Record<string, string> = {
  "Champions League": "Şampiyonlar Ligi",
  "Champions League qualifying": "Şampiyonlar Ligi elemesi",
  "Europa League": "Avrupa Ligi",
  "Europa League qualifying": "Avrupa Ligi elemesi",
  "Conference League qualifying": "Konferans Ligi elemesi",
  "European playoffs": "Avrupa play-off",
  "Championship playoffs": "Şampiyonluk play-off",
  Promotion: "Üst lige çıkış",
  "Promotion playoff": "Çıkış play-off",
  "Promotion playoffs": "Çıkış play-off",
  "Promotion Playoffs": "Çıkış play-off",
  Relegated: "Küme düşme hattı",
  Relegation: "Küme düşme hattı",
  "Relegation playoff": "Düşme play-off",
  "Relegation playoffs": "Düşme play-off",
  "Qualifies for round of 16": "Son 16'ya direkt",
  "Knockout phase playoffs - seeded": "Eleme play-off (seri başı)",
  "Knockout phase playoffs - unseeded": "Eleme play-off",
  Eliminated: "Elendi",
  "Qualifies for MLS Cup Playoffs - Round One Best-of-3 series": "MLS play-off (1. tur)",
  "Qualifies for MLS Cup Playoffs - Wild Card Matches": "MLS play-off (wild card)",
};

export function noteLabel(desc: string | null | undefined): string {
  if (!desc) return "";
  return NOTE_TR[desc] ?? desc;
}

function num(v: number | null): string {
  return v === null ? "–" : String(v);
}

function signed(v: number | null): string {
  if (v === null) return "–";
  return v > 0 ? `+${v}` : String(v);
}

export default function StandingsTable({
  entries,
  highlight = [],
  compact = false,
}: {
  entries: StandingEntry[];
  highlight?: string[];
  compact?: boolean;
}) {
  const legend = new Map<string, string>();
  entries.forEach((e) => {
    if (e.note?.description && e.note.color && !legend.has(e.note.description)) legend.set(e.note.description, e.note.color);
  });
  const cell = compact ? "px-1.5 py-1.5" : "px-2 py-2";
  return (
    <div>
      <div className="overflow-x-auto">
        <table className={`w-full text-sm ${compact ? "min-w-[420px]" : "min-w-[560px]"}`}>
          <thead className="text-right text-xs text-muted">
            <tr className="border-b border-line">
              <th className={`${cell} w-8 text-left font-medium`}>#</th>
              <th className={`${cell} text-left font-medium`}>Takım</th>
              <th className={`${cell} font-medium`} title="Oynanan">O</th>
              <th className={`${cell} font-medium`} title="Galibiyet">G</th>
              <th className={`${cell} font-medium`} title="Beraberlik">B</th>
              <th className={`${cell} font-medium`} title="Mağlubiyet">M</th>
              {!compact && (
                <>
                  <th className={`${cell} font-medium`} title="Attığı gol">A</th>
                  <th className={`${cell} font-medium`} title="Yediği gol">Y</th>
                </>
              )}
              <th className={`${cell} font-medium`} title="Averaj">AV</th>
              <th className={`${cell} font-medium`} title="Puan">P</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => {
              const hl = highlight.includes(e.team_id);
              return (
                <tr key={e.team_id} className={`border-b border-line/60 last:border-0 ${hl ? "bg-surface-3 font-semibold" : ""}`}>
                  <td className={`${cell} text-left`}>
                    <span
                      className="num inline-flex items-center gap-1.5"
                      title={e.note?.description ? noteLabel(e.note.description) : undefined}
                    >
                      <span
                        aria-hidden
                        className="inline-block h-4 w-1 rounded-full"
                        style={{ background: e.note?.color ?? "transparent" }}
                      />
                      {num(e.rank)}
                    </span>
                  </td>
                  <td className={`${cell} text-left`}>
                    <span className="flex min-w-0 items-center gap-2">
                      <Crest team={{ name: e.name, logo: e.logo }} size={compact ? 18 : 22} />
                      <span className="truncate">{e.name}</span>
                      {hl && <span className="sr-only">(bu maçın takımı)</span>}
                      {e.deductions ? (
                        <span className="num shrink-0 rounded border border-critical/40 px-1 text-[0.65rem] text-critical-ink" title="Puan silme">
                          −{e.deductions}
                        </span>
                      ) : null}
                    </span>
                  </td>
                  <td className={`${cell} num text-right`}>{num(e.played)}</td>
                  <td className={`${cell} num text-right`}>{num(e.won)}</td>
                  <td className={`${cell} num text-right`}>{num(e.drawn)}</td>
                  <td className={`${cell} num text-right`}>{num(e.lost)}</td>
                  {!compact && (
                    <>
                      <td className={`${cell} num text-right`}>{num(e.gf)}</td>
                      <td className={`${cell} num text-right`}>{num(e.ga)}</td>
                    </>
                  )}
                  <td className={`${cell} num text-right`}>{signed(e.gd)}</td>
                  <td className={`${cell} num text-right font-semibold`}>{num(e.points)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {legend.size > 0 && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-2">
          {[...legend.entries()].map(([desc, color]) => (
            <li key={desc} className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-3 w-1 rounded-full" style={{ background: color }} />
              {noteLabel(desc)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
