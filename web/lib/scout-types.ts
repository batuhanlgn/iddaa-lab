// Scout raporu tipleri — backend/app/scout.py build_scout() dönüşüyle birebir (SCOUT_VERSION "scout-v1").

/** Maddenin işaret ettiği taraf. "neutral" maddeler bilgi taşır, hükme ağırlık katmaz. */
export type ScoutSide = "home" | "away" | "draw" | "goals_over" | "goals_under" | "neutral";

export type ScoutSectionKey = "guc" | "form" | "lig" | "h2h" | "profil" | "piyasa" | "risk";

/** Kanıt bölümleri (risk hariç): hüküm ekseni bunların net desteğine bakar. */
export type ScoutEvidenceKey = Exclude<ScoutSectionKey, "risk">;

export interface ScoutItem {
  text: string;
  side: ScoutSide;
  /** 0–1. Risk bölümünde riskin önemi; diğer bölümlerde kanıtın gücü. */
  weight: number;
}

export interface ScoutSection {
  key: ScoutSectionKey;
  title: string;
  /** Bölüm için veri var mı (yoksa note nedenini söyler). */
  available: boolean;
  note: string | null;
  items: ScoutItem[];
}

export interface ScoutPick {
  market_key: string;
  key: string;
  label: string;
  line: string | null;
  /** iddaa sonuç adı ("1", "0 ve 2", "Üst", "Var"...) */
  selection: string;
  /** Okunur seçim metni ("Arsenal kazanır (MS 2)") */
  selection_text: string;
  odd: number;
  p_model: number;
  p_market: number;
  /** Muhafazakâr harman olasılığı (coupons.candidates ile aynı) */
  p_safe: number;
  ev: number | null;
  family_validated: boolean;
  /** Modelin kendi önerisiyle (coupons.model_pick) aynı seçim mi; değilse aynı yönde temkinli karşılık ya da gol pazarı */
  same_as_model_pick: boolean;
}

export type ScoutConfidence = "yüksek" | "orta";

export interface ScoutVerdictPick {
  verdict: "oneri";
  headline: string;
  reason: string;
  confidence: ScoutConfidence;
  pick: ScoutPick;
}

export interface ScoutVerdictPass {
  verdict: "pas";
  headline: string;
  reason: string;
  confidence: null;
  pick: null;
}

export type ScoutVerdict = ScoutVerdictPick | ScoutVerdictPass;

export interface ScoutAxisSignal {
  /** Eksende değerlendirilen yön; maç kapsam dışıysa null */
  direction: ScoutSide | null;
  agree: ScoutEvidenceKey[];
  disagree: ScoutEvidenceKey[];
  /** Bölüm başına net destek (-1.5 … 1.5) */
  nets: Partial<Record<ScoutEvidenceKey, number>>;
}

export interface ScoutTeamRef {
  id: string;
  name: string;
}

export interface ScoutReportData {
  version: string;
  match_id: string;
  home: ScoutTeamRef;
  away: ScoutTeamRef;
  summary: string;
  verdict: ScoutVerdict;
  signals: { result: ScoutAxisSignal; goals: ScoutAxisSignal };
  sections: ScoutSection[];
  risk_total: number;
}
