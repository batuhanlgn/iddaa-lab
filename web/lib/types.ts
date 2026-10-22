// Arka uç (FastAPI) yanıt tipleri — backend/app/api.py, model/pipeline.py ve coupons.py ile birebir.
import type { ScoutReportData } from "./scout-types";
import type { SimilarOddsData } from "./similar-types";

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

export interface ScoutBrief {
  verdict: "oneri" | "pas";
  headline: string;
  reason: string;
  confidence: "yüksek" | "orta" | null;
  selection_text: string | null;
  odd: number | null;
  p_model: number | null;
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
  /** Scout hükmü özeti (api._scout_brief); öneri yalnız kanıtlar aynı yönü gösterdiğinde */
  scout?: ScoutBrief | null;
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
  /** null: tek yönlü sunulan pazar (ör. yalnız "Kırmızı kart: Evet"), marj hesaplanamaz */
  margin: number | null;
  family_validated: boolean;
  fetched_at: string;
  outcomes: IddaaOutcome[];
}

export type AltUst = { Alt: number; "Üst": number };
export type ThreeWay = { "1": number; "0": number; "2": number };

/** Korner modeli: takım başına beklenen korner + ortak dağılımdan çizgi olasılıkları (eski yüklerde yalnız lines) */
export interface CornerModel {
  mu_home: number;
  mu_away: number;
  k: number;
  phi?: number;
  lines: Record<string, AltUst>;
  home_lines?: Record<string, AltUst>;
  away_lines?: Record<string, AltUst>;
  kdc?: ThreeWay;
  ranges?: Record<string, number>;
  handicap?: Record<string, { "1": number; "2": number }>;
}

/** Kart modeli (iddaa sayımı: sarı 1, kırmızı 2; ikinci sarıdan kırmızı 1+2) */
export interface CardModel {
  mu_home: number;
  mu_away: number;
  k: number;
  phi: number;
  lines: Record<string, AltUst>;
  ht_lines: Record<string, AltUst>;
  ht_share: number | null;
  kdc: ThreeWay;
  p_red: number | null;
  red_home: number | null;
  red_away: number | null;
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
    lineup_adj?: { beta: number; home: number; away: number; home_ratio: number | null; away_ratio: number | null };
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
  corners?: CornerModel | null;
  cards?: CardModel | null;
  sim?: Simulation;
  odds_history_ms: { outcome_no: number; odd: number; fetched_at: string }[];
  form: Record<"home" | "away", FormMatch[]>;
  /** Güncellemeden önce dışa aktarılmış eski statik veride bulunmayabilir */
  standings?: MatchStandings | null;
  h2h?: H2HMatch[];
  similar?: SimilarOddsData | null;
  scout?: ScoutReportData | null;
}

// ---------------------------------------------------------------- puan durumu ve karşılıklı geçmiş

export interface StandingEntry {
  team_id: string;
  name: string;
  abbreviation: string | null;
  logo: string | null;
  played: number | null;
  won: number | null;
  drawn: number | null;
  lost: number | null;
  gf: number | null;
  ga: number | null;
  gd: number | null;
  points: number | null;
  deductions: number | null;
  rank: number | null;
  note: { color: string | null; description: string | null } | null;
}

export interface StandingsGroup {
  name: string;
  entries: StandingEntry[];
}

export interface LeagueStandings {
  slug: string;
  name: string;
  country: string;
  is_cup: boolean;
  season: string | null;
  season_year: number | null;
  groups: StandingsGroup[];
  fetched_at: string;
}

export interface StandingsResponse {
  leagues: LeagueStandings[];
}

export interface MatchStandings {
  season: string | null;
  group: string;
  entries: StandingEntry[];
  fetched_at: string | null;
}

export interface H2HMatch {
  id: string;
  date_utc: string;
  league: string;
  league_name: string;
  home_id: string;
  away_id: string;
  home_name: string;
  away_name: string;
  home_goals: number;
  away_goals: number;
  extra_time: boolean;
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

export type CouponKind =
  | "deger" | "olasilik" | "dengeli" | "oyuncu" | "tekli" | "sistem_2_3" | "sistem_3_4" | "surpriz" | "korner" | "kart";

export interface GeneratedCoupon extends CouponCombination {
  kind: CouponKind;
  system?: SystemInfo;
  title: string;
  description: string;
  empty_reason: string | null;
  experimental: boolean;
  /** false: scout onayı aranmayan türler (korner, kart); eski yüklerde yok */
  scout_gated?: boolean;
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
  /** korner / kart: pazar türü ve çizgi bazında değerlendirme (backtest.aux_validation) */
  markets?: Record<string, AuxCriterion>;
  lines?: Record<string, AuxCriterion>;
}

export interface FamilyValidation {
  validated?: boolean;
  ece?: number;
  n?: number;
  gain?: number;
  /** korner / kart: pazar türü ve çizgi bayrakları (çizgi: pazar türü doğrulandı ve o çizgide kazanç > 0) */
  markets?: Record<string, { validated: boolean; n: number; gain: number; ece: number }>;
  lines?: Record<string, { validated: boolean; n: number; gain: number; ece: number }>;
}

export interface AuxCriterion {
  n: number;
  model_logloss: number;
  base_logloss: number;
  gain: number;
  ece: number;
  validated: boolean;
}

export interface AuxTuningFamily {
  grid: { xi: number; sigma: number; k_total: number; phi: number; mean_logloss: number; n: number }[];
  chosen?: Record<string, number>;
  n_dist?: number;
  note?: string;
}

export interface Backtest {
  created_at: string;
  tune_window: [string, string];
  eval_window: [string, string];
  params: Record<string, number>;
  tuning: { xi: number; sigma: number; ms_logloss: number; n: number }[];
  summary: Record<string, FamilySummary>;
  by_league: Record<string, { n: number; model_logloss: number; base_logloss: number }>;
  family_validation: Record<string, FamilyValidation>;
  dispersion?: Record<string, number>;
  /** backend/app/backtest.py tune_aux (korner / kart / kırmızı kart ayarı); eski yüklerde yok */
  aux_tuning?: {
    korner?: AuxTuningFamily;
    kart?: AuxTuningFamily;
    kirmizi?: { grid: { xi: number; sigma: number; logloss: number; n: number }[]; chosen: Record<string, number> };
    params?: Record<string, Record<string, number>>;
  };
  alpha_tuning?: { alpha: number; goal_families_logloss: number }[];
  score_calibration?: { t: number; g: number; used: boolean; eval_ll_raw: number; eval_ll_cal: number };
  /** backend/app/backtest.py tune_xg_weight */
  xg_tuning?: {
    xg_weight: number;
    accepted: boolean;
    n_tune_xg_matches: number;
    grid: { xg_weight: number; goal_families_logloss: number }[];
    tune_best?: number;
    note?: string;
    val_ll_without?: number;
    val_ll_with?: number;
    val_bootstrap?: { mean_gain: number; ci90: [number, number]; p_better: number };
  };
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

export interface ScoutBtSummary {
  n: number;
  hits?: number;
  hit_rate?: number;
  avg_odd?: number;
  p_model?: number;
  p_market?: number;
  edge_vs_market?: number;
  roi_close?: number;
  roi_iddaa?: number;
  roi_iddaa_ci95?: [number, number];
}

export interface ScoutBtGroups {
  scout: ScoutBtSummary;
  scout_yuksek: ScoutBtSummary;
  scout_orta: ScoutBtSummary;
  model_all: ScoutBtSummary;
  model_on_pas: ScoutBtSummary;
  model_on_oneri: ScoutBtSummary;
  scout_by_market: Record<string, ScoutBtSummary>;
}

/** backend/app/scout_backtest.py run_scout_backtest */
export interface ScoutBacktest {
  created_at: string;
  window: [string, string];
  n_matches: number;
  skipped: Record<string, number>;
  iddaa_margins: Record<string, number>;
  verdicts: Record<string, number>;
  pas_reasons: [string, number][];
  all: ScoutBtGroups;
  first_half: ScoutBtGroups;
  second_half: ScoutBtGroups;
  by_league: Record<string, ScoutBtSummary>;
  league_names: Record<string, string>;
  notes: string[];
}

export interface PerformanceResponse {
  live_picks: LivePicksSummary | null;
  scout_backtest?: ScoutBacktest | null;
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

// ---------------------------------------------------------------- Spor Toto (backend/app/sportoto.py toto_view)

export type TotoOutcome = "1" | "0" | "2";
export type TotoSource = "harman" | "model" | "piyasa" | "yok";
/** olasilik: 15 bilme olasılığı · kalabalik: beklenen ikramiye · kalabalik_2: beklenen ikramiye, Kupon 2 ile ortak kolon yok */
export type TotoKind = "olasilik" | "kalabalik" | "kalabalik_2";

export interface TotoEvent {
  event_no: number;
  event_name: string;
  home: string | null;
  away: string | null;
  competition: string;
  kickoff_utc: string | null;
  picks: TotoOutcome[];
  cover: number;
  kind: "banko" | "çift" | "üçlü";
  source: TotoSource;
  probs: Record<TotoOutcome, number>;
  confidence: Confidence | null;
  match_id: string | null;
  league_name: string | null;
  odds: Record<TotoOutcome, number> | null;
  model: Record<TotoOutcome, number> | null;
  market: Record<TotoOutcome, number> | null;
  result: string | null;
  winner: TotoOutcome | null;
  /** oynanma oranı (totokazan, toplamı 1); kalabalık verisi yoksa null */
  crowd: Record<TotoOutcome, number> | null;
}

/** backend/app/sportoto_crowd.py Market.to_json — N (etkin kalabalık kolon) ve kademe havuzu tahmini */
export interface TotoMarket {
  n_columns: number;
  pools: Record<string, number>;
  carry: number;
  n_weeks: number;
  basis: { cycle_no: number; n_eff: number; winners: Record<string, number>; base_pools: Record<string, number>; price: number | null }[];
  notes: string[];
  /** kalabalığın kazanan sayısı için PB alt sınırı (önceki haftalarda en sürprizli gerçekleşen sonuç) */
  pb_floor: Record<string, number>;
  floor_weeks: number;
  /** beklenen ikramiyede sonuç olasılığı p^a · oynanma^(1−a) */
  blend_a: number;
  blend_weeks: number;
}

export interface TotoDiffItem {
  o: TotoOutcome;
  p: number;
  crowd: number;
}

export interface TotoCoupon {
  kind: TotoKind;
  title: string;
  description: string;
  cycle_no: number;
  budget: number;
  column_price: number;
  max_column: number;
  pool_source: "iddaa" | "varsayılan";
  columns: number;
  cost: number;
  p15: number;
  p_at_least: Record<string, number>;
  expected_hits: number;
  events: TotoEvent[];
  n_no_data: number;
  locked: boolean;
  updated_at: string;
  status: "open" | "settled";
  hits: number | null;
  prize: number | null;
  winning_columns: Record<string, number> | null;
  /** kalabalık modeline göre beklenen ikramiye (TL); kalabalık verisi yoksa null */
  expected_prize: number | null;
  expected_prize_se?: number | null;
  expected_prize_by_tier: Record<string, number> | null;
  market?: TotoMarket;
  crowd_source?: { fetched_at: string; tk_week_id: number | null; tk_name: string | null; source: string };
  /** yalnız kalabalık kuponları: Kupon 1'den farklı maçlar ve kısa açıklama */
  diffs?: { event_no: number; from: TotoOutcome[]; to: TotoOutcome[]; added: TotoDiffItem[]; removed: TotoDiffItem[] }[];
  why?: string;
  common_columns_with_kalabalik?: number;
  /** yalnız Kupon 1: kalabalık kuponlarının durumu */
  crowd_status?: { available: boolean; reason: string | null };
}

export interface TotoCouponSlot {
  kind: TotoKind;
  title: string;
  description: string;
  coupon: TotoCoupon | null;
  /** kupon yoksa nedeni */
  reason: string | null;
}

export interface TotoCrowd {
  available: boolean;
  reason: string | null;
  fetched_at: string | null;
  tk_name: string | null;
  source: string;
  events: ({ event_no: number } & Record<TotoOutcome, number>)[];
}

export interface TotoKindHistory {
  settled: number;
  avg_hits: number | null;
  best_hits: number | null;
  total_cost: number;
  total_prize: number;
}

export interface TotoWeek {
  cycle_no: number;
  program_name: string | null;
  payin_begin_utc: string | null;
  payin_end_utc: string;
  dividends: { tier: number; winners: number; amount: number }[] | null;
  status: "open" | "settled";
  fetched_at: string;
}

/** backend/app/sportoto_backtest.py run_toto_backtest — strateji özeti */
export interface TotoBtStrategy {
  n_weeks: number;
  cost: number;
  prize: number;
  net: number;
  roi: number;
  avg_hits: number;
  median_hits?: number;
  weeks_12plus: number;
  weeks_13plus: number;
  weeks_14plus: number;
  weeks_15: number;
  prize_weeks: number;
  max_prize?: number;
  hit_distribution?: Record<string, number>;
  /** yalnız "rastgele": 200 tekrarın dağılımı */
  n_runs?: number;
  roi_p05?: number;
  roi_p50?: number;
  roi_p95?: number;
  prize_p50?: number;
  share_runs_below_canli?: number;
  share_runs_no_prize?: number;
}

export interface TotoBtWeek {
  cycle_no: number;
  program_name: string | null;
  payin_end_utc: string;
  column_price: number;
  hits: number;
  columns: number;
  cost: number;
  prize: number;
  expected_hits: number;
  n_by_source: Record<string, number>;
  strategies: Record<string, { hits: number; prize: number; cost: number }>;
}

export interface TotoBtProbScore {
  n: number;
  logloss: number;
  brier: number;
  top_pred: number;
  top_hit: number;
}

export type TotoBacktestResponse =
  | { available: false }
  | {
      available: true;
      created_at: string;
      window: { from_cycle: number; to_cycle: number; from: string; to: string; n_weeks: number };
      budget: number;
      price_today: number;
      columns: number;
      price_schedule: { from_cycle: number; to_cycle: number | null; price: number; source: string }[];
      excluded: { cycle_no: number; reason: string }[];
      coverage: { n_events: number; share: Record<"harman" | "model" | "piyasa" | "yok", number> };
      strategies: Record<"canli" | "piyasa" | "model" | "rastgele", TotoBtStrategy>;
      segments: Record<"canli" | "piyasa" | "model", Record<string, TotoBtStrategy>>;
      calibration: {
        expected_hits: number;
        actual_hits: number;
        same_matches: Record<"model" | "piyasa" | "harman", TotoBtProbScore>;
        p_at_least_expected_weeks: Record<string, number>;
        p_at_least_observed_weeks: Record<string, number>;
      };
      best_weeks: { cycle_no: number; program_name: string | null; hits: number; prize: number; cost: number }[];
      worst_weeks: { cycle_no: number; program_name: string | null; hits: number; prize: number; cost: number }[];
      weeks: TotoBtWeek[];
      notes: string[];
    };

export interface TotoResponse {
  week: TotoWeek | null;
  coupons: TotoCouponSlot[];
  crowd: TotoCrowd | null;
  /** Kalabalık kuponları (2/3) açık mı (config.TOTO_CROWD_COUPONS); eski statik veride yok */
  crowd_coupons?: boolean;
  weekly_cost: number;
  pool: { column_price: number; max_column: number; source: "iddaa" | "varsayılan"; budget: number; weekly_budget: number };
  history: { by_kind: Partial<Record<TotoKind, TotoKindHistory>>; total_cost: number; total_prize: number };
  generated_at: string;
}

/** backend/app/sportoto_crowd.py run_crowd_backtest — tür özeti */
export interface TotoCrowdBtKind extends TotoBtStrategy {
  expected_prize: number;
  expected_roi: number | null;
  realized_over_expected: number | null;
  expected_by_tier: Record<string, number>;
  realized_by_tier: Record<string, number>;
  p12_expected_weeks: number;
  p15_expected_weeks: number;
  avg_columns: number;
}

export interface TotoCrowdBtWeek {
  cycle_no: number;
  program_name: string | null;
  column_price: number;
  market: { n_columns: number; pools: Record<string, number>; carry: number; n_weeks: number; blend_a: number; blend_weeks: number };
  realized_n_eff: number | null;
  n_by_source: Record<string, number>;
  coupons: Record<
    TotoKind,
    { hits: number; columns: number; cost: number; prize: number; expected_prize: number; p15: number; p12: number; winning_columns: Record<string, number> }
  >;
}

export type TotoCrowdBacktestResponse =
  | { available: false }
  | {
      available: true;
      created_at: string;
      window: { from_cycle: number | null; to_cycle: number | null; n_weeks: number };
      columns: number;
      mc_samples: number;
      kinds: Record<TotoKind, TotoCrowdBtKind>;
      combined: { cost: number; prize: number; roi: number | null };
      n_estimate: { median_ratio_realized_over_est: number | null; n: number };
      excluded: { cycle_no: number; reason: string | null }[];
      tk_odds_fallback_events: number;
      weeks: TotoCrowdBtWeek[];
      notes: string[];
    };
