"use client";

import { useSyncExternalStore } from "react";

// Kullanıcının kendi kuponu: bu tarayıcıya özel kolaylık (localStorage). Kalıcı/paylaşılan durum değildir.
export interface Pick {
  match_id: string;
  market_key: string;
  outcome_no: number;
  // görüntüleme için
  home: string;
  away: string;
  date_utc: string;
  label: string;
  line: string | null;
  outcome_name: string;
  odd: number;
  // değerlendirme (tarayıcıda; sunucu gerekmez)
  p_model: number;
  p_market: number;
  p_safe: number;
  ev: number;
  mbs: number;
  family_validated: boolean;
  odds_at: string;
  /** false: oyuncu tahmini; oran model adil oranıdır, EV hesaplanmaz */
  has_market?: boolean;
}

const KEY = "iddaa-lab-coupon-v2";
const EVT = "iddaa-lab-coupon-change";
const EMPTY: Pick[] = [];
let cache: { raw: string | null; value: Pick[] } = { raw: null, value: EMPTY };

function isPick(x: unknown): x is Pick {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.match_id === "string" &&
    typeof o.market_key === "string" &&
    typeof o.outcome_no === "number" &&
    typeof o.odd === "number" &&
    typeof o.p_safe === "number" &&
    typeof o.mbs === "number"
  );
}

function read(): Pick[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return EMPTY;
  }
  if (raw === cache.raw) return cache.value;
  let value: Pick[] = EMPTY;
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    value = Array.isArray(parsed) ? parsed.filter(isPick) : EMPTY;
  } catch {
    value = EMPTY;
  }
  cache = { raw, value };
  return value;
}

function write(picks: Pick[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(picks));
  } catch {
    return false;
  }
  window.dispatchEvent(new Event(EVT));
  return true;
}

function subscribe(cb: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) cb();
  };
  window.addEventListener(EVT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function useCoupon(): Pick[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

export function isPicked(picks: Pick[], matchId: string, marketKey: string, outcomeNo: number): boolean {
  return picks.some((p) => p.match_id === matchId && p.market_key === marketKey && p.outcome_no === outcomeNo);
}

/** Aynı maçtan tek seçim: yeni seçim o maçın eski seçiminin yerine geçer. Dönüş: kaydedildi mi. */
export function togglePick(pick: Pick): boolean {
  const cur = read();
  if (isPicked(cur, pick.match_id, pick.market_key, pick.outcome_no)) {
    return write(cur.filter((p) => !(p.match_id === pick.match_id && p.market_key === pick.market_key && p.outcome_no === pick.outcome_no)));
  }
  return write([...cur.filter((p) => p.match_id !== pick.match_id), pick]);
}

export function removePick(matchId: string): boolean {
  return write(read().filter((p) => p.match_id !== matchId));
}

export interface CouponEval {
  total_odds: number;
  prob: number;
  ev: number | null;
  mbs_required: number;
  mbs_ok: boolean;
  warnings: string[];
}

/** Kupon toplamları: oranlar ve (bağımsızlık varsayımıyla) muhafazakâr olasılıklar çarpılır. */
export function evaluate(picks: Pick[]): CouponEval {
  const total_odds = picks.reduce((a, p) => a * p.odd, 1);
  const prob = picks.reduce((a, p) => a * p.p_safe, 1);
  const mbs_required = picks.reduce((a, p) => Math.max(a, p.mbs), 1);
  const warnings: string[] = [];
  if (picks.some((p) => !p.family_validated)) warnings.push("Bazı seçimler backtest'te doğrulanmamış pazar ailelerinden");
  if (picks.length < mbs_required) warnings.push(`MBS kuralı: en az ${mbs_required} maçlık kupon gerekir`);
  const allMarket = picks.every((p) => p.has_market !== false);
  if (!allMarket) warnings.push("Oyuncu seçimlerinin iddaa oranı yok: toplam oran adil orandır, beklenen değer hesaplanmaz");
  return {
    total_odds,
    prob,
    ev: allMarket ? prob * total_odds - 1 : null,
    mbs_required,
    mbs_ok: picks.length >= mbs_required,
    warnings,
  };
}

export function clearPicks(): boolean {
  return write([]);
}
