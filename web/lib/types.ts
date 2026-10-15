// Arka uç (FastAPI) yanıt tipleri — backend/app/api.py, model/pipeline.py ve coupons.py ile birebir.

export type Confidence = "yüksek" | "orta" | "düşük" | "yok";

export interface Team {
  id: string;
  name: string;
  short_name?: string | null;
  abbreviation?: string | null;
  logo?: string | null;
  color?: string | null;
}

export interface MatchInfo {
  id: string;
  league: string;
  league_name: string;
  country: string;
  date_utc: string;
  venue: string | null;
  neutral: boolean;
  state: string;
  home: Team;
  away: Team;
  lineup_confirmed: boolean;
}

/** Model önerisi: ana pazarlarda modelin piyasa kadar/daha fazla güvendiği en olası seçim */
export interface BestValue {
  label: string;
  line: string | null;
  name: string;
  odd: number;
  ev: number;
  p_blend: number;
  validated: boolean;
}

export interface MatchRow {
  match: MatchInfo;
  covered: boolean;
  coverage_note?: string;
  model_version?: string;
  created_at?: string;
  lambda_home?: number;
  lambda_away?: number;
  confidence?: Confidence;
  ms?: Record<string, number>;
  au25?: Record<string, number>;
  kg?: Record<string, number>;
  top_score?: { home: number; away: number; p: number } | null;
  has_sim?: boolean;
  iddaa?: {
    event_id: number;
    mbs: number | null;
    ms_odds: Record<string, number> | null;
    best_value: BestValue | null;
    n_markets: number;
  };
  top_players?: { side: "home" | "away"; name: string; p_sot_1: number; p_goal: number }[];
}

export interface MarketOnlyRow {
  event_id: number;
  home: string;
  away: string;
  kickoff_utc: string;
  competition: string | null;
  country_code: string | null;
  mbs: number | null;
  ms_odds: Record<string, number> | null;
  ms_market_prob: Record<string, number> | null;
}

export interface MatchesResponse {
  items: MatchRow[];
  market_only: MarketOnlyRow[];
  leagues: { slug: string; name: string; country: string }[];
  generated_at: string;
}

export interface ModelOutcome {
  name: string;
  p_model: number;
}

export interface StandardMarket {
  key: string;
  label: string;
  family: string;
  line: string | null;
  outcomes: ModelOutcome[];
}

export interface IddaaOutcome {
  no: number;
  name: string;
  odd: number;
  p_model: number;
  p_market: number;
  /** Piyasa skor matrisi kurulamazsa (MS pazarı yok) null */
  p_blend: number | null;
  /** min(matris harmanı, pazar içi harman): değer/EV için muhafazakâr olasılık */
  p_safe: number | null;
  ev: number | null;
  ev_model: number;
}

export interface IddaaMarket {
  market_key: string;
  key: string;
  label: string;
  family: string;
  line: string | null;
  mbs: number | null;
  margin: number;
  family_validated: boolean;
  fetched_at: string;
  outcomes: IddaaOutcome[];
}

export interface DistSummary {
  mean: number;
  p10: number;
  p50: number;
  p90: number;
  at_least: Record<string, number>;
  pmf: Record<string, number>;
}

export interface SimPlayer {
  player_id: string;
  name: string;
  pos_group: "G" | "D" | "M" | "F";
  position: string | null;
  p_play: number;
  p_start: number;
  exp_minutes: number;
  exp_shots: number;
  p_shots_1: number;
  p_shots_2: number;
  p_shots_3: number;
  exp_sot: number;
  p_sot_1: number;
  p_sot_2: number;
  p_goal: number;
  p_goal_2: number;
  rate_shots_p90: number;
  rate_acc: number;
  rate_conv: number;
  minutes_seen: number;
  confirmed_starter: boolean | null;
  flags: string[];
}

export interface SimTeam {
  team_id: string;
  u: number;
  v: number;
  shots_mu_prior: number;
  shots: DistSummary;
  shots_on_target: DistSummary;
  own_goals_for: number;
  players: SimPlayer[];
  players_available: boolean;
}

export type SimEventType = "shot" | "sot" | "goal" | "own_goal_for" | "sub_in";

export interface SimEvent {
  minute: number;
  side: "home" | "away";
  team_id: string;
  player_id: string | null;
  player: string | null;
  type: SimEventType;
}

export interface Scenario {
  score: [number, number];
  ht: [number, number];
  stats: Record<"home" | "away", { shots: number; sot: number }>;
  events: SimEvent[];
}

export interface Simulation {
  n_sims: number;
  teams: Record<"home" | "away", SimTeam>;
  scenarios: Scenario[];
  notes: {
    home: string[];
    away: string[];
    lineup_source: Record<"home" | "away", "resmi" | "tahmini">;
  };
}

export interface FormMatch {
  id: string;
  date_utc: string;
  league: string;
  home_id: string;
  away_id: string;
  home_goals: number;
  away_goals: number;
  hn: string;
  an: string;
  is_home: boolean;
}

export interface MatchDetail {
  match: MatchInfo;
  covered: boolean;
  coverage_note?: string;
  model_version: string;
  created_at: string;
  model?: {
    lambda_home: number;
    lambda_away: number;
    rho: number;
    p1: number;
    confidence: Confidence;
    confidence_notes: string[];
    as_of: string;
    params: Record<string, number>;
    blend_weight: number;
    blend_calibrated: boolean;
    family_validation: Record<string, boolean>;
  };
  score_matrix?: { size: number; p: number[][]; other: number };
  top_scores?: { home: number; away: number; p: number }[];
  markets?: StandardMarket[];
  iddaa?: {
    event_id: number;
    mbs: number | null;
    markets: IddaaMarket[];
    market_model: { lambda_home: number; lambda_away: number; kl: number; ms_market_fit: number[]; ms_blend: number[] } | null;
  } | null;
  corners?: { mu_home: number; mu_away: number; k: number; lines: Record<string, { Alt: number; "Üst": number }> } | null;
  sim?: Simulation;
  odds_history_ms: { outcome_no: number; odd: number; fetched_at: string }[];
  form: Record<"home" | "away", FormMatch[]>;
}

export interface Selection {
  match_id: string;
  iddaa_event_id: number;
  home: string;
  away: string;
  league_name: string;
  date_utc: string;
  market_key: string;
  key: string;
  label: string;
  family: string;
  line: string | null;
  outcome_no: number;
  outcome_name: string;
  odd: number;
  p_model: number;
  p_market: number;
  p_blend: number;
  /** null: oyuncu tahmini (iddaa'da oranı yok) */
  ev: number | null;
  mbs: number;
  confidence: Confidence;
  model_version: string;
  family_validated: boolean;
  has_market: boolean;
}

export interface CouponCombination {
  selections: Selection[];
  total_odds: number;
  prob: number;
  ev: number | null;
  mbs_required: number;
  mbs_ok: boolean;
  independence_assumed: boolean;
  warnings: string[];
}

export interface SystemInfo {
  k: number;
  n: number;
  combos: { idx: number[]; odds: number; prob: number }[];
  cost: number;
  expected_return: number;
  min_win_odds: number;
}

export type CouponKind = "deger" | "olasilik" | "dengeli" | "oyuncu" | "tekli" | "sistem_2_3" | "sistem_3_4" | "surpriz";

export interface GeneratedCoupon extends CouponCombination {
  kind: CouponKind;
  system?: SystemInfo;
  title: string;
  description: string;
  empty_reason: string | null;
  experimental: boolean;
  archived_id?: number;
  /** Günün kuponu: bu saatte kilitlendi, gün boyu değişmez */
  locked_at?: string;
}

export interface CouponsResponse {
  created_at: string;
  days: number;
  n_matches_considered: number;
  n_candidates: number;
  blend_validated: boolean;
  family_validation: Record<string, { validated?: boolean; gain?: number; ece?: number; n?: number }>;
  coupons: GeneratedCoupon[];
}

export interface CustomCouponResponse extends CouponCombination {
  missing: string[];
}

export type CouponStatus = "open" | "won" | "lost" | "void";

export interface CouponHistoryItem {
  id: number;
  created_at: string;
  kind: string;
  status: CouponStatus;
  settled_at: string | null;
  total_odds: number;
  prob: number;
  ev: number;
  stake: number;
  payout: number | null;
  selections: Selection[];
  selection_results: (string | null)[] | null;
  experimental: boolean;
  system: SystemInfo | null;
}

export interface CouponKindSummary {
  n: number;
  settled: number;
  won: number;
  staked: number;
  returned: number;
  expected_hits: number;
  roi: number | null;
}

export interface CouponHistoryResponse {
  items: CouponHistoryItem[];
  summary: Record<string, CouponKindSummary>;
}

export interface TopPlayer extends SimPlayer {
  match_id: string;
  date_utc: string;
  league_name: string;
  team: string;
  team_logo: string | null;
  opponent: string;
  side: "home" | "away";
  lineup_source: "resmi" | "tahmini";
}

export interface TopPlayersResponse {
  items: TopPlayer[];
  total: number;
}

export interface CalibrationBin {
  bin_lo: number;
  bin_hi: number;
  pred: number;
  obs: number;
  n: number;
}

export interface FamilySummary {
  n: number;
  model_logloss: number;
  model_brier: number;
  base_logloss: number;
  base_brier: number;
  simple_logloss?: number;
  calibration: CalibrationBin[];
  ece?: number;
}

export interface Backtest {
  created_at: string;
  tune_window: [string, string];
  eval_window: [string, string];
  params: Record<string, number>;
  tuning: { xi: number; sigma: number; ms_logloss: number; n: number }[];
  summary: Record<string, FamilySummary>;
  by_league: Record<string, { n: number; model_logloss: number; base_logloss: number }>;
  family_validation: Record<string, { validated?: boolean; ece?: number; n?: number; gain?: number }>;
  dispersion?: Record<string, number>;
  alpha_tuning?: { alpha: number; goal_families_logloss: number }[];
  score_calibration?: { t: number; g: number; used: boolean; eval_ll_raw: number; eval_ll_cal: number };
}

export interface PlayerMetric {
  n: number;
  model_logloss: number;
  base_logloss: number;
  mean_pred: number;
  mean_obs: number;
  calibration: CalibrationBin[];
  calibrated?: boolean;
  cv_ll_raw?: number | null;
  cv_ll_cal?: number | null;
}

export interface TrackingGroup {
  n: number;
  n_clv: number;
  clv_mean: number | null;
  ev_vs_close_mean: number | null;
  beat_close_pct: number | null;
  settled: number;
  won: number;
  void: number;
  hit_rate: number | null;
  expected_hit_rate: number | null;
  roi: number | null;
}

export interface TrackedPick {
  match_id: string;
  date_utc: string;
  home: string;
  away: string;
  label: string;
  line: string | null;
  name: string;
  odd: number;
  p_model: number;
  close_odd: number | null;
  clv_odds: number | null;
  result: string | null;
}

export interface LivePicksSummary {
  n: number;
  settled: number;
  won: number;
  hit_rate: number | null;
  expected_hit_rate: number | null;
  roi: number | null;
  by_market: Record<string, { n: number; won: number; hit_rate: number | null; expected_hit_rate: number | null; roi: number | null }>;
  recent: {
    match_id: string; home: string; away: string; created_at: string; minute: number; score: string; market: string;
    sov: string; outcome: string; odd: number; p_model: number; ev: number; status: string;
  }[];
}

export interface PerformanceResponse {
  live_picks: LivePicksSummary | null;
  tracking: { updated_at: string; groups: Record<string, TrackingGroup>; recent_picks: TrackedPick[]; family_labels: Record<string, string> } | null;
  player_calibration: Record<string, { a: number; b: number; use: boolean; cv_ll_raw: number | null; cv_ll_cal: number | null; n: number }> | null;
  backtest: Backtest | null;
  player_backtest: { created_at: string; window_start: string; metrics: Record<string, PlayerMetric> } | null;
  blend_calibration: {
    status: "veri_yok" | "yetersiz_veri" | "kalibre" | "dogrulanamadi";
    validated?: boolean;
    n_fit?: number;
    n_holdout?: number;
    holdout_blend_logloss?: number;
    holdout_market_logloss?: number;
    holdout_model_logloss?: number;
    n: number;
    required: number;
    weight?: number;
    best_w?: number;
    default_weight: number;
    model_logloss?: number;
    market_logloss?: number;
    curve?: { w: number; logloss: number }[];
    updated_at: string;
  } | null;
  coupons: Record<string, CouponKindSummary>;
  league_names: Record<string, string>;
}

export interface JobRun {
  id: number;
  job: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "error";
  message: string | null;
}

export interface StatusResponse {
  jobs: JobRun[];
  running: JobRun | null;
  counts: Record<string, number>;
  model_version: string | null;
  model_as_of: string | null;
  iddaa_last_fetch: string | null;
}

export interface CoverageLeague {
  slug: string;
  name: string;
  country: string;
  is_cup: boolean;
  detail_months: number;
  total: number;
  completed: number;
  summaries_ok: number;
  summaries_missing: number;
  with_ht: number;
  first: string | null;
  last_completed: string | null;
  upcoming: number;
  team_stat_rows: number;
  shots_rows: number;
  corners_rows: number;
  iddaa_linked: number;
}

export interface CoverageResponse {
  leagues: CoverageLeague[];
}
