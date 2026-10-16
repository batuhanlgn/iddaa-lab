import type { TotoEvent, TotoKind, TotoOutcome } from "./types";

/** Bayi formundaki sıra: 1, X, 2 */
export const TOTO_OUTS: TotoOutcome[] = ["1", "0", "2"];

export const KIND_SHORT: Record<TotoKind, string> = {
  olasilik: "K1",
  kalabalik: "K2",
  kalabalik_2: "K3",
};

export function outLabel(o: TotoOutcome): string {
  return o === "0" ? "X" : o;
}

/** İşaretler bayi sırasıyla: ["2", "1"] -> "12" */
export function pickCode(picks: TotoOutcome[]): string {
  return TOTO_OUTS.filter((o) => picks.includes(o)).map(outLabel).join("");
}

/** Bayi için kupon satırı: "1: 1X · 2: 2 · …" */
export function bayiLine(events: Pick<TotoEvent, "event_no" | "picks">[]): string {
  return events.map((e) => `${e.event_no}: ${pickCode(e.picks)}`).join(" · ");
}
