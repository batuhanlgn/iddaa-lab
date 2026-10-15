// Canlı model (tarayıcıda): maç öncesi beklenen goller + anlık skor/dakika/kırmızı kart -> maç sonu dağılımı.
//
// Kalan goller iki aşamada Poisson: ilk yarının kalanı (g1) ve ikinci yarının kalanı (g2).
//   r1 = ilk yarıdan kalan gol payı, r2 = ikinci yarıdan kalan gol payı (lig 1. yarı payı p1 ile; yarı içinde düzgün)
//   ilk yarı skoru I = anlık + g1 (ilk yarıdaysa), maç sonu X = I + g2
// Kırmızı kart: cezalı takımın kalan gol hızı x0.67, rakibinki x1.25 (kart başına; literatürdeki tipik etki).
// Pazar mantığı backend/app/model/markets.py outcome_mask ile birebir.

export const RED_OWN = 0.67;
export const RED_OPP = 1.25;
const N = 7; // aşama başına en fazla 6 gol (kalan sürede fazlası ihmal edilebilir; kuyruk son hücreye eklenir)

export interface LiveState {
  started: boolean;
  finished: boolean;
  period: number;        // 1, 2 (uzatmalar 90'da sabitlenir)
  halftime: boolean;
  minute: number;        // 0-90
  home: number;
  away: number;
  htHome: number | null; // ilk yarı skoru biliniyorsa
  htAway: number | null;
  redHome: number;
  redAway: number;
}

export interface PreModel {
  lambda_home: number;
  lambda_away: number;
  p1: number;
  cal_g: number;
}

function pois(lam: number): number[] {
  const out: number[] = [];
  let p = Math.exp(-lam);
  let tot = 0;
  for (let k = 0; k < N; k++) {
    out.push(p);
    tot += p;
    p = (p * lam) / (k + 1);
  }
  out[N - 1] += Math.max(0, 1 - tot);
  return out;
}

export interface Rates {
  r1h: number; // kalan ilk yarı beklenen golleri
  r1a: number;
  r2h: number; // kalan ikinci yarı beklenen golleri
  r2a: number;
}

export function remainingShares(s: LiveState, p1: number): { s1: number; s2: number } {
  if (!s.started) return { s1: p1, s2: 1 - p1 };
  if (s.finished) return { s1: 0, s2: 0 };
  if (s.period <= 1 && !s.halftime) {
    const m = Math.min(Math.max(s.minute, 0), 45);
    return { s1: p1 * Math.max(45 - m, 0.5) / 45, s2: 1 - p1 };
  }
  if (s.halftime) return { s1: 0, s2: 1 - p1 };
  const m = Math.min(Math.max(s.minute, 45), 90);
  return { s1: 0, s2: ((1 - p1) * Math.max(90 - m, 1)) / 45 };
}

export function liveRates(pre: PreModel, s: LiveState): Rates {
  const { s1, s2 } = remainingShares(s, pre.p1);
  const g = pre.cal_g || 1;
  const adjH = Math.pow(RED_OWN, s.redHome) * Math.pow(RED_OPP, s.redAway);
  const adjA = Math.pow(RED_OWN, s.redAway) * Math.pow(RED_OPP, s.redHome);
  const lh = pre.lambda_home * g * adjH;
  const la = pre.lambda_away * g * adjA;
  return { r1h: lh * s1, r1a: la * s1, r2h: lh * s2, r2a: la * s2 };
}

/** Ortak dağılım üzerinde bir koşulun olasılığı. f(X, Y, I, J, remH, remA) */
export type Cond = (X: number, Y: number, I: number, J: number, remH: number, remA: number) => boolean;

export interface LiveDist {
  prob: (f: Cond) => number;
}

export function liveDist(pre: PreModel, s: LiveState): LiveDist {
  const r = liveRates(pre, s);
  const p1h = pois(r.r1h), p1a = pois(r.r1a), p2h = pois(r.r2h), p2a = pois(r.r2a);
  const inFirst = !s.started || (s.period <= 1 && !s.halftime);
  const baseI = inFirst ? s.home : (s.htHome ?? s.home);
  const baseJ = inFirst ? s.away : (s.htAway ?? s.away);
  return {
    prob(f: Cond): number {
      let tot = 0;
      for (let a = 0; a < N; a++)
        for (let b = 0; b < N; b++) {
          const w1 = p1h[a] * p1a[b];
          if (w1 < 1e-12) continue;
          const I = inFirst ? s.home + a : baseI;
          const J = inFirst ? s.away + b : baseJ;
          for (let c = 0; c < N; c++)
            for (let d = 0; d < N; d++) {
              const w = w1 * p2h[c] * p2a[d];
              if (w < 1e-14) continue;
              const X = s.home + a + c;
              const Y = s.away + b + d;
              if (f(X, Y, I, J, a + c, b + d)) tot += w;
            }
        }
      return tot;
    },
  };
}

// ---------------------------------------------------------------- pazar sonuçları (outcome_mask karşılığı)

type Res = "1" | "0" | "2";
const res = (x: number, y: number): Res => (x > y ? "1" : x === y ? "0" : "2");

/** iddaa pazar anahtarı + çizgi + sonuç adı -> koşul (tanınmazsa null). */
export function outcomeCond(key: string, line: string | null, name: string): Cond | null {
  const L = line != null && line !== "" ? Number(line) : null;
  const n = name.trim();
  const kgVar = (X: number, Y: number) => X > 0 && Y > 0;
  switch (key) {
    case "ms":
      return ["1", "0", "2"].includes(n) ? (X, Y) => res(X, Y) === n : null;
    case "cs":
    case "iy_cs": {
      const parts = n.replace(/\s/g, "").split("ve");
      if (parts.length !== 2) return null;
      return key === "cs"
        ? (X, Y) => parts.includes(res(X, Y))
        : (_X, _Y, I, J) => parts.includes(res(I, J));
    }
    case "iy":
      return (_X, _Y, I, J) => res(I, J) === n;
    case "iy2":
      return (X, Y, I, J) => res(X - I, Y - J) === n;
    case "kg":
      return n === "Var" ? (X, Y) => kgVar(X, Y) : n === "Yok" ? (X, Y) => !kgVar(X, Y) : null;
    case "iy_kg":
      return n === "Var" ? (_X, _Y, I, J) => I > 0 && J > 0 : n === "Yok" ? (_X, _Y, I, J) => !(I > 0 && J > 0) : null;
    case "au":
    case "iy_au":
    case "ev_au":
    case "dep_au": {
      if (L == null) return null;
      const v = (X: number, Y: number, I: number, J: number) =>
        key === "au" ? X + Y : key === "iy_au" ? I + J : key === "ev_au" ? X : Y;
      if (n === "Alt") return (X, Y, I, J) => v(X, Y, I, J) < L;
      if (n === "Üst") return (X, Y, I, J) => v(X, Y, I, J) > L;
      return null;
    }
    case "hnd":
      return L == null ? null : (X, Y) => res(X + L, Y) === n;
    case "iyms": {
      const [a, b] = n.split("/");
      return a && b ? (X, Y, I, J) => res(I, J) === a && res(X, Y) === b : null;
    }
    case "tc":
      return n === "Tek" ? (X, Y) => (X + Y) % 2 === 1 : n === "Çift" ? (X, Y) => (X + Y) % 2 === 0 : null;
    case "tg": {
      const r: Record<string, [number, number]> = { "0-1 gol": [0, 1], "2-3 gol": [2, 3], "4-5 gol": [4, 5], "6+ gol": [6, 99] };
      const rg = r[n];
      return rg ? (X, Y) => X + Y >= rg[0] && X + Y <= rg[1] : null;
    }
    case "cgy":
      return (X, Y, I, J) => {
        const g1 = I + J, g2 = X + Y - I - J;
        return n === "1." ? g1 > g2 : n === "Eşit" ? g1 === g2 : n === "2." ? g1 < g2 : false;
      };
    case "ms_au":
    case "ms_kg":
    case "au_kg": {
      const [p, q] = n.split(" ve ").map((x) => x.trim());
      const lineV = L ?? 2.5;
      const au = (X: number, Y: number, w: string) => (w === "Alt" ? X + Y < lineV : w === "Üst" ? X + Y > lineV : null);
      const kg = (X: number, Y: number, w: string) => (w === "Var" ? kgVar(X, Y) : w === "Yok" ? !kgVar(X, Y) : null);
      if (key === "ms_au") return (X, Y) => res(X, Y) === p && au(X, Y, q) === true;
      if (key === "ms_kg") return (X, Y) => res(X, Y) === p && kg(X, Y, q) === true;
      return (X, Y) => au(X, Y, p) === true && kg(X, Y, q) === true;
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------- seçim durumu

export type PickStatus = "bekliyor" | "tutuyor" | "tutmuyor" | "tuttu" | "yattı" | "takip yok";

/** Gol sayıları yalnızca artar: bazı pazarlar maç bitmeden kesinleşir. */
function certainty(key: string, line: string | null, name: string, s: LiveState): "won" | "lost" | null {
  const L = line != null && line !== "" ? Number(line) : null;
  const tot = s.home + s.away;
  const htKnown = s.period >= 2 || s.halftime || s.finished;
  if (key === "au" && L != null) {
    if (name === "Üst" && tot > L) return "won";
    if (name === "Alt" && tot > L) return "lost";
  }
  if ((key === "ev_au" || key === "dep_au") && L != null) {
    const v = key === "ev_au" ? s.home : s.away;
    if (name === "Üst" && v > L) return "won";
    if (name === "Alt" && v > L) return "lost";
  }
  if (key === "kg" && s.home > 0 && s.away > 0) return name === "Var" ? "won" : "lost";
  if (key === "tg") {
    const hi: Record<string, number> = { "0-1 gol": 1, "2-3 gol": 3, "4-5 gol": 5 };
    if (hi[name] != null && tot > hi[name]) return "lost";
  }
  if ((key === "iy" || key === "iy_kg" || key === "iy_au" || key === "iy_cs") && htKnown && s.htHome != null && s.htAway != null) {
    const c = outcomeCond(key, line, name);
    if (c) return c(s.home, s.away, s.htHome, s.htAway, 0, 0) ? "won" : "lost";
  }
  return null;
}

export function pickStatus(key: string, line: string | null, name: string, s: LiveState | null): PickStatus {
  if (!s || !s.started) return "bekliyor";
  const cond = outcomeCond(key, line, name);
  if (!cond) return "takip yok";
  const I = s.htHome ?? s.home;
  const J = s.htAway ?? s.away;
  if (s.finished) return cond(s.home, s.away, I, J, 0, 0) ? "tuttu" : "yattı";
  const c = certainty(key, line, name, s);
  if (c === "won") return "tuttu";
  if (c === "lost") return "yattı";
  return cond(s.home, s.away, I, J, 0, 0) ? "tutuyor" : "tutmuyor";
}

/** Seçimin maç sonunda tutma olasılığı (canlı model). */
export function pickLiveProb(key: string, line: string | null, name: string, pre: PreModel | null, s: LiveState | null): number | null {
  if (!pre || !s) return null;
  const cond = outcomeCond(key, line, name);
  if (!cond) return null;
  if (s.finished) return null;
  return liveDist(pre, s).prob(cond);
}

// ---------------------------------------------------------------- iddaa canlı pazarları

/** Sıradaki gol (golün sırası n): ev / olmaz / deplasman olasılıkları. */
export function nextGoalProbs(pre: PreModel, s: LiveState): { home: number; none: number; away: number } {
  const r = liveRates(pre, s);
  const h = r.r1h + r.r2h;
  const a = r.r1a + r.r2a;
  const t = h + a;
  const none = Math.exp(-t);
  return t > 0 ? { home: ((1 - none) * h) / t, none, away: ((1 - none) * a) / t } : { home: 0, none: 1, away: 0 };
}

/** Kalan süre sonucu: yalnız bundan sonra atılacak gollere göre 1/0/2. */
export function restOfMatchProbs(pre: PreModel, s: LiveState): Record<"1" | "0" | "2", number> {
  const d = liveDist(pre, s);
  return {
    "1": d.prob((_X, _Y, _I, _J, rh, ra) => rh > ra),
    "0": d.prob((_X, _Y, _I, _J, rh, ra) => rh === ra),
    "2": d.prob((_X, _Y, _I, _J, rh, ra) => rh < ra),
  };
}
