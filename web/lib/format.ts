const TZ = "Europe/Istanbul";

export function pct(p: number | null | undefined, digits = 0): string {
  if (p == null || Number.isNaN(p)) return "–";
  return `%${(p * 100).toFixed(digits)}`;
}

export function odd(o: number | null | undefined): string {
  if (o == null) return "–";
  return o.toFixed(2);
}

export function signedPct(x: number, digits = 1): string {
  const v = (x * 100).toFixed(digits);
  return x > 0 ? `+%${v}` : x < 0 ? `-%${v.slice(1)}` : `%${v}`;
}

export function fairOdd(p: number): string {
  return p > 0 ? (1 / p).toFixed(2) : "–";
}

export function kickoff(iso: string): string {
  return new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function dayKey(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

export function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = dayKey(new Date().toISOString());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  const k = dayKey(iso);
  const base = new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" }).format(d);
  if (k === today) return `Bugün · ${base}`;
  if (k === tomorrow) return `Yarın · ${base}`;
  return base;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "hiç";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "az önce";
  if (s < 3600) return `${Math.round(s / 60)} dk önce`;
  if (s < 86400) return `${Math.round(s / 3600)} sa önce`;
  return `${Math.round(s / 86400)} gün önce`;
}

export function compact(n: number): string {
  return new Intl.NumberFormat("tr-TR", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export const OUTCOME_LABEL: Record<string, string> = { "1": "Ev", "0": "Beraberlik", "2": "Deplasman" };

/** Çizgi metni. Handikap iddaa notasyonuyla: sov = ev sahibine eklenen gol -> +1 "(1:0)", -2 "(0:2)". */
export function lineText(labelOrKey: string, line: string | null): string {
  if (line == null || line === "") return "";
  if (labelOrKey === "hnd" || labelOrKey.startsWith("Handikap")) {
    const v = Number(line);
    if (!Number.isFinite(v)) return line;
    return v >= 0 ? `(${v}:0)` : `(0:${-v})`;
  }
  return line;
}

export function marketLine(label: string, line: string | null): string {
  const t = lineText(label, line);
  return t ? `${label} ${t}` : label;
}
