// Canlı veri: tarayıcı ESPN (skor/dakika/olay) ve iddaa (canlı oran) kaynaklarını doğrudan çeker (ikisi de CORS'a açık).
import type { LiveState } from "./live-model";

// site.web.api: ESPN web sitesinin kullandığı uç; tarayıcıdan CORS ile güvenilir çalışıyor (site.api bazı tarayıcı
// parmak izlerini bot koruması nedeniyle CORS başlığı olmadan 403 ile reddediyor)
const ESPN = "https://site.web.api.espn.com/apis/site/v2/sports/soccer";
const IDDAA_LIVE = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0";

export interface LiveBaseItem {
  id: string;
  league: string;
  league_name: string;
  country: string;
  date_utc: string;
  home: { id: string; name: string; short_name?: string | null; logo?: string | null };
  away: { id: string; name: string; short_name?: string | null; logo?: string | null };
  model: { lambda_home: number; lambda_away: number; p1: number; cal_g: number; confidence: string };
  pre_ms: Record<string, number> | null;
  iddaa: { event_id: number; home_name: string; away_name: string } | null;
  pick: { label: string; line: string | null; name: string; key: string; odd: number; p_model: number } | null;
}

export interface LiveBase {
  generated_at: string;
  items: LiveBaseItem[];
}

export interface LiveEvent {
  minute: string;
  base: number;
  side: "home" | "away";
  type: "goal" | "own_goal" | "penalty" | "yellow" | "red";
  player: string | null;
}

export interface EspnLive {
  state: LiveState;
  clock: string;
  detail: string;
  events: LiveEvent[];
}

export interface IddaaLiveMarket {
  st: number;
  sov: string | null;
  outcomes: { name: string; odd: number }[];
}

export interface IddaaLive {
  id: number;
  home: string;
  away: string;
  kickoff: number;
  score: [number, number] | null;
  markets: IddaaLiveMarket[];
}

function clockBase(s: string | undefined): number {
  const m = /^(\d+)/.exec(s ?? "");
  return m ? Number(m[1]) : 0;
}

/** ESPN gününü (ABD Doğu saati) maç başlangıcından türet. */
export function espnDate(iso: string): string {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  return p.replaceAll("-", "");
}

interface EspnCompetitor {
  homeAway: string;
  score?: string;
  team?: { id?: string };
}
interface EspnDetail {
  type?: { text?: string };
  clock?: { displayValue?: string };
  team?: { id?: string };
  scoringPlay?: boolean;
  redCard?: boolean;
  yellowCard?: boolean;
  ownGoal?: boolean;
  penaltyKick?: boolean;
  athletesInvolved?: { displayName?: string }[];
}
interface EspnEvent {
  id: string;
  status?: { displayClock?: string; period?: number; type?: { state?: string; completed?: boolean; name?: string; shortDetail?: string } };
  competitions?: { competitors?: EspnCompetitor[]; details?: EspnDetail[] }[];
}

function parseEspnEvent(e: EspnEvent): EspnLive | null {
  const comp = e.competitions?.[0];
  if (!comp) return null;
  const home = comp.competitors?.find((c) => c.homeAway === "home");
  const away = comp.competitors?.find((c) => c.homeAway === "away");
  if (!home || !away) return null;
  const st = e.status?.type ?? {};
  const state = st.state ?? "pre";
  const started = state === "in" || state === "post";
  const finished = state === "post" && Boolean(st.completed);
  const period = e.status?.period ?? 0;
  const halftime = (st.name ?? "").includes("HALFTIME");
  const hs = Number(home.score ?? 0) || 0;
  const as_ = Number(away.score ?? 0) || 0;
  const homeId = home.team?.id;
  const events: LiveEvent[] = [];
  for (const d of comp.details ?? []) {
    const side: "home" | "away" = d.team?.id === homeId ? "home" : "away";
    const minute = d.clock?.displayValue ?? "";
    const base = clockBase(minute);
    const player = d.athletesInvolved?.[0]?.displayName ?? null;
    if (d.scoringPlay) events.push({ minute, base, side, type: d.ownGoal ? "own_goal" : d.penaltyKick ? "penalty" : "goal", player });
    else if (d.redCard) events.push({ minute, base, side, type: "red", player });
    else if (d.yellowCard) events.push({ minute, base, side, type: "yellow", player });
  }
  // İlk yarı skoru: gol olaylarından; kendi kalesine gollerin hangi takıma yazıldığı belirsiz olabildiği için
  // olay toplamı resmi skorla tutacak biçimde atanır (tutmazsa İY bilinmiyor sayılır)
  const goals = events.filter((x) => x.type !== "red" && x.type !== "yellow");
  let htHome: number | null = null;
  let htAway: number | null = null;
  for (const flipOwn of [false, true]) {
    let fh = 0, fa = 0, h1 = 0, a1 = 0;
    for (const g of goals) {
      const side = g.type === "own_goal" && flipOwn ? (g.side === "home" ? "away" : "home") : g.side;
      if (side === "home") fh++;
      else fa++;
      if (g.base <= 45) {
        if (side === "home") h1++;
        else a1++;
      }
    }
    if (fh === hs && fa === as_) {
      htHome = h1;
      htAway = a1;
      break;
    }
  }
  const knownHt = period >= 2 || halftime || finished;
  const minute = finished ? 90 : halftime ? 45 : Math.min(clockBase(e.status?.displayClock), 90);
  return {
    state: {
      started, finished, period: Math.min(period, 2), halftime, minute, home: hs, away: as_,
      htHome: knownHt ? htHome : null, htAway: knownHt ? htAway : null,
      redHome: events.filter((x) => x.type === "red" && x.side === "home").length,
      redAway: events.filter((x) => x.type === "red" && x.side === "away").length,
    },
    clock: e.status?.displayClock ?? "",
    detail: st.shortDetail ?? "",
    events,
  };
}

export async function fetchEspn(items: LiveBaseItem[], signal?: AbortSignal): Promise<Map<string, EspnLive>> {
  const groups = new Map<string, Set<string>>();
  for (const it of items) {
    const k = `${it.league}|${espnDate(it.date_utc)}`;
    if (!groups.has(k)) groups.set(k, new Set());
    groups.get(k)!.add(it.id);
  }
  const out = new Map<string, EspnLive>();
  await Promise.all(
    [...groups.entries()].map(async ([k, ids]) => {
      const [league, date] = k.split("|");
      try {
        const r = await fetch(`${ESPN}/${league}/scoreboard?dates=${date}`, { signal, cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as { events?: EspnEvent[] };
        for (const e of j.events ?? []) {
          if (!ids.has(e.id)) continue;
          const p = parseEspnEvent(e);
          if (p) out.set(e.id, p);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") throw err;
        // tek lig hatası diğerlerini durdurmasın; bir sonraki turda tekrar denenir
      }
    }),
  );
  return out;
}

interface IddaaRaw {
  i: number;
  hn: string;
  an: string;
  d: number;
  s?: number;
  m?: { t: number; st: number; sov?: string; o?: { n?: string; odd?: number }[] }[];
}

export async function fetchIddaaLive(signal?: AbortSignal): Promise<IddaaLive[]> {
  const r = await fetch(IDDAA_LIVE, { signal, cache: "no-store" });
  if (!r.ok) throw new Error(`iddaa canlı bülten: ${r.status}`);
  const j = (await r.json()) as { isSuccess?: boolean; data?: { events?: IddaaRaw[] } };
  if (!j.isSuccess) throw new Error("iddaa canlı bülten başarısız yanıt");
  const now = Date.now() / 1000;
  const out: IddaaLive[] = [];
  for (const e of j.data?.events ?? []) {
    if (!e.m?.length || e.d > now + 60) continue;
    const markets: IddaaLiveMarket[] = [];
    let score: [number, number] | null = null;
    for (const m of e.m) {
      if (m.t !== 4) continue;
      const outs = (m.o ?? []).filter((o) => o.n && o.odd && o.odd > 1).map((o) => ({ name: String(o.n), odd: Number(o.odd) }));
      if (m.st === 23 && m.sov && /^\d+:\d+$/.test(m.sov)) {
        const [a, b] = m.sov.split(":").map(Number);
        score = [a, b];
      }
      if (outs.length) markets.push({ st: m.st, sov: m.sov ?? null, outcomes: outs });
    }
    out.push({ id: e.i, home: e.hn, away: e.an, kickoff: e.d, score, markets });
  }
  return out;
}

const TR: Record<string, string> = { ç: "c", ğ: "g", ı: "i", İ: "i", ö: "o", ş: "s", ü: "u" };
export function normName(s: string): string {
  return s
    .replace(/[çğıİöşü]/g, (c) => TR[c] ?? c)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Canlı iddaa etkinliğini maça bağla: aynı kimlik ya da iddaa'nın kendi takım adları + başlama saati. */
export function matchIddaa(item: LiveBaseItem, live: IddaaLive[]): IddaaLive | null {
  if (!item.iddaa) return null;
  const byId = live.find((e) => e.id === item.iddaa!.event_id);
  if (byId) return byId;
  const kick = Date.parse(item.date_utc) / 1000;
  const h = normName(item.iddaa.home_name);
  const a = normName(item.iddaa.away_name);
  return live.find((e) => Math.abs(e.kickoff - kick) <= 20 * 60 && normName(e.home) === h && normName(e.away) === a) ?? null;
}

export interface PlayerLive {
  shots: number;
  sot: number;
  goals: number;
  played: boolean;
}

export async function fetchPlayerStats(league: string, matchId: string, signal?: AbortSignal): Promise<Map<string, PlayerLive>> {
  const out = new Map<string, PlayerLive>();
  const r = await fetch(`${ESPN}/${league}/summary?event=${matchId}`, { signal, cache: "no-store" });
  if (!r.ok) return out;
  const j = (await r.json()) as {
    rosters?: { roster?: { athlete?: { id?: string }; starter?: boolean; subbedIn?: boolean; stats?: { name: string; value?: number }[] }[] }[];
  };
  for (const team of j.rosters ?? []) {
    for (const p of team.roster ?? []) {
      const id = p.athlete?.id;
      if (!id) continue;
      const st = Object.fromEntries((p.stats ?? []).map((x) => [x.name, Number(x.value ?? 0)]));
      out.set(String(id), {
        shots: st.totalShots ?? 0, sot: st.shotsOnTarget ?? 0, goals: st.totalGoals ?? 0,
        played: Boolean(p.starter || p.subbedIn),
      });
    }
  }
  return out;
}
