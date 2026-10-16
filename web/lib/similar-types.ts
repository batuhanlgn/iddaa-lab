// "Benzer oran" yanıt tipi — backend/app/similar_odds.py find_similar / find_similar_probs dönüşüyle birebir.

/** 1X2 anahtarları: "1" ev, "0" beraberlik, "2" deplasman */
export type Outcome1X2 = "1" | "0" | "2";
export type Triple = Record<Outcome1X2, number>;

export type SimilarSource = "football-data" | "iddaa";

export interface SimilarTarget {
  /** "iddaa": bülten MS oranları; "model": iddaa oranı yokken modelin MS olasılıkları */
  basis: "iddaa" | "model";
  odds: Triple | null;
  /** marjı arındırılmış hedef olasılıklar */
  probs: Triple;
  fair_odds: Triple;
}

export interface SimilarExample {
  source: SimilarSource;
  date: string; // YYYY-MM-DD
  league: string;
  league_name: string;
  country: string;
  home: string;
  away: string;
  hg: number;
  ag: number;
  hthg: number | null;
  htag: number | null;
  odds: Triple;
  similarity: number;
}

export interface SimilarScore {
  score: string; // "2-1"
  hg: number;
  ag: number;
  count: number;
  share: number;
}

export interface SimilarLeague {
  league: string;
  name: string;
  country: string;
  count: number;
}

export interface SimilarOddsData {
  n: number;
  pool_size: number;
  low_sample: boolean;
  min_sample: number;
  similarity: { min: number; definition: string };
  target: SimilarTarget;
  outcomes: Triple | null;
  outcomes_ci95: Record<Outcome1X2, [number, number]> | null;
  /** eşleşen maçların ortalama adil olasılıkları (piyasanın o maçlarda beklediği) */
  pool_implied: Triple | null;
  top_scores: SimilarScore[];
  over25: number | null;
  btts: number | null;
  avg_goals: number | null;
  ht: { n: number; outcomes: Triple } | null;
  sources: Record<SimilarSource, number>;
  leagues: SimilarLeague[];
  date_range: { from: string; to: string } | null;
  closest: SimilarExample[];
  recent: SimilarExample[];
}
