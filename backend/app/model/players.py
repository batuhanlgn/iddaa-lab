"""Oyuncu oranları (şut/90, SoT/şut, gol/SoT) ve kadro-dakika senaryo parametreleri.

Tüm tahminler yalnızca as_of öncesi veriden üretilir (backtest sızıntısı yok).
Büzülme: pozisyon grubuna göre veri tabanlı prior (Gamma-Poisson / Beta-Binomial eşleniği).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..sources.espn import pos_group as _pos_group

POS_GROUPS = ("G", "D", "M", "F")
# Prior gücü (eşdeğer gözlem): şut hızı 90'lık maç cinsinden, oranlar şut / SoT cinsinden
ALPHA_RATE = 4.0
ALPHA_ACC = 12.0
ALPHA_CONV = 15.0
PLAYER_XI = 0.0019     # oyuncu oranları için zaman sönümü (yarı ömür ~1 yıl)
LINEUP_DECAY = 0.75    # kadro eğilimi: son maçtan geriye doğru ağırlık çarpanı
LINEUP_MATCHES = 10


@dataclass
class PositionPrior:
    shots_p90: float
    acc: float
    conv: float


@dataclass
class PlayerRates:
    player_id: str
    name: str
    pos_group: str
    position: str | None
    shots_p90: float
    acc: float            # SoT / şut
    conv: float           # gol / SoT
    minutes_seen: float   # ağırlıksız toplam dakika (veri miktarı göstergesi)
    shots_seen: int


@dataclass
class LineupEntry:
    player_id: str
    name: str
    pos_group: str
    position: str | None
    start_prob: float
    sub_prob: float
    start_exit: list[int]       # ilk 11'de başladığı maçlardaki çıkış dakikaları (90 = tamamladı)
    sub_entry: list[int]        # yedekten girdiği maçlardaki giriş dakikaları
    flags: list[str] = field(default_factory=list)
    confirmed_starter: bool | None = None  # resmi kadro açıklandıysa


@dataclass
class TeamPlayerContext:
    team_id: str
    lineup: list[LineupEntry]
    rates: dict[str, PlayerRates]
    recent_matches: int
    lineup_confirmed: bool
    data_ok: bool
    notes: list[str]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class PlayerStore:
    """as_of öncesi oyuncu-maç satırlarını bellekte tutar; takım bağlamlarını üretir."""

    def __init__(self, con: sqlite3.Connection, as_of: datetime, lookback_days: int = 760) -> None:
        self.as_of = as_of
        before = (as_of - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")  # sonucu bilinen maçlar
        since = datetime.fromtimestamp(as_of.timestamp() - lookback_days * 86400).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = con.execute(
            """SELECT pm.*, m.date_utc, p.name AS pname
               FROM player_match pm
               JOIN matches m ON m.id = pm.match_id
               JOIN players p ON p.id = pm.player_id
               WHERE m.completed=1 AND m.summary_status='ok' AND m.extra_time=0 AND m.date_utc < ? AND m.date_utc >= ?
               ORDER BY m.date_utc""",
            (before, since),
        ).fetchall()
        self.rows = rows
        self.by_player: dict[str, list[sqlite3.Row]] = defaultdict(list)
        self.by_team_match: dict[str, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
        self.team_match_dates: dict[str, dict[str, str]] = defaultdict(dict)
        pos_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in rows:
            self.by_player[r["player_id"]].append(r)
            self.by_team_match[r["team_id"]][r["match_id"]].append(r)
            self.team_match_dates[r["team_id"]][r["match_id"]] = r["date_utc"]
            pos = (r["position"] or "").upper()
            if pos and pos != "SUB":
                pos_counts[r["player_id"]][pos] += 1
        # Kanonik pozisyon: oyuncunun "SUB" dışındaki en sık pozisyonu (yedekten girişler pozisyon taşımaz)
        self.canon_pos: dict[str, str | None] = {}
        self.canon_group: dict[str, str] = {}
        for pid in self.by_player:
            pc = pos_counts.get(pid)
            best = max(pc.items(), key=lambda kv: kv[1])[0] if pc else None
            self.canon_pos[pid] = best
            self.canon_group[pid] = _pos_group(best) if best else "M"
        self.priors = self._position_priors()

    def _position_priors(self) -> dict[str, PositionPrior]:
        acc: dict[str, list[float]] = {g: [0.0, 0.0, 0.0, 0.0] for g in POS_GROUPS}  # dakika, şut, sot, gol
        for r in self.rows:
            if r["minutes"] <= 0 or r["shots"] is None:
                continue
            a = acc[self.canon_group.get(r["player_id"], "M")]
            a[0] += r["minutes"]
            a[1] += r["shots"] or 0
            a[2] += r["shots_on_target"] or 0
            a[3] += r["goals"] or 0
        defaults = {"G": (0.01, 0.3, 0.3), "D": (0.6, 0.3, 0.25), "M": (1.1, 0.32, 0.28), "F": (2.2, 0.38, 0.33)}
        out = {}
        for g in POS_GROUPS:
            mins, sh, sot, gl = acc[g]
            d = defaults[g]
            out[g] = PositionPrior(
                shots_p90=(sh / (mins / 90)) if mins > 900 else d[0],
                acc=(sot / sh) if sh > 50 else d[1],
                conv=(gl / sot) if sot > 50 else d[2],
            )
        return out

    def player_rates(self, player_id: str) -> PlayerRates | None:
        hist = self.by_player.get(player_id)
        if not hist:
            return None
        last = hist[-1]
        g = self.canon_group.get(player_id, "M")
        pr = self.priors.get(g, self.priors["M"])
        w_min = w_sh = w_sot = w_gl = 0.0
        raw_min = 0.0
        raw_sh = 0
        for r in hist:
            if r["minutes"] <= 0 or r["shots"] is None:
                continue
            days = (self.as_of - _dt(r["date_utc"])).total_seconds() / 86400
            w = float(np.exp(-PLAYER_XI * max(days, 0)))
            w_min += w * r["minutes"]
            w_sh += w * (r["shots"] or 0)
            w_sot += w * (r["shots_on_target"] or 0)
            w_gl += w * (r["goals"] or 0)
            raw_min += r["minutes"]
            raw_sh += r["shots"] or 0
        rate = (w_sh + ALPHA_RATE * pr.shots_p90) / (w_min / 90 + ALPHA_RATE)
        acc = (w_sot + ALPHA_ACC * pr.acc) / (w_sh + ALPHA_ACC)
        conv = (w_gl + ALPHA_CONV * pr.conv) / (w_sot + ALPHA_CONV)
        # Veri gürültüsüne karşı tutarlılık sınırları
        acc = float(np.clip(acc, 0.05, 0.9))
        conv = float(np.clip(conv, 0.02, 0.9))
        return PlayerRates(player_id, last["pname"], g, self.canon_pos.get(player_id), float(rate), acc, conv, raw_min, raw_sh)

    def team_context(self, team_id: str, confirmed: dict[str, bool] | None = None) -> TeamPlayerContext:
        """confirmed: resmi kadro (oyuncu id -> ilk 11 mi). None ise geçmişten tahmin."""
        matches = self.by_team_match.get(team_id, {})
        dates = self.team_match_dates.get(team_id, {})
        recent = sorted(matches, key=lambda m: dates[m], reverse=True)[:LINEUP_MATCHES]
        notes: list[str] = []
        if len(recent) < 3:
            notes.append("Takımın oyuncu detaylı maç verisi 3'ten az: oyuncu tahminleri gösterilmez")
        weights = np.array([LINEUP_DECAY**k for k in range(len(recent))])
        wsum = float(weights.sum()) if len(recent) else 1.0

        info: dict[str, dict] = {}
        for k, mid in enumerate(recent):
            for r in matches[mid]:
                d = info.setdefault(
                    r["player_id"],
                    {"name": r["pname"], "pos": self.canon_group.get(r["player_id"], "M"),
                     "position": self.canon_pos.get(r["player_id"]), "start": 0.0,
                     "sub": 0.0, "bench_or_absent": 0.0, "last_seen": k, "exits": [], "entries": [], "red_last": False},
                )
                d["last_seen"] = min(d["last_seen"], k)
                if r["starter"]:
                    d["start"] += weights[k]
                    if r["min_off"] is not None and r["minutes_quality"] == "exact":
                        d["exits"].append(int(r["min_off"]))
                elif r["min_on"] is not None and r["minutes"] > 0:
                    d["sub"] += weights[k]
                    if r["minutes_quality"] == "exact":
                        d["entries"].append(int(r["min_on"]))
                if k == 0 and (r["red"] or 0) > 0:
                    d["red_last"] = True

        lineup: list[LineupEntry] = []
        for pid, d in info.items():
            start_p = d["start"] / wsum
            non_start_w = max(wsum - d["start"], 1e-9)
            sub_p = d["sub"] / non_start_w
            flags: list[str] = []
            if d["last_seen"] >= 6:
                start_p *= 0.05
                sub_p *= 0.05
                flags.append(f"Son {d['last_seen']} maçta kadroda yok (uzun sakatlık/transfer olabilir)")
            elif d["last_seen"] >= 3:
                start_p *= 0.3
                sub_p *= 0.3
                flags.append(f"Son {d['last_seen']} maçta kadroda yok (sakatlık/ceza olabilir)")
            if d["red_last"]:
                flags.append("Son maçta kırmızı kart gördü: müsaitlik belirsiz")
            lineup.append(
                LineupEntry(pid, d["name"], d["pos"], d["position"], float(np.clip(start_p, 0, 1)), float(np.clip(sub_p, 0, 1)),
                            d["exits"], d["entries"], flags)
            )
        lineup_confirmed = False
        if confirmed:
            lineup_confirmed = True
            known = {e.player_id for e in lineup}
            for e in lineup:
                if e.player_id in confirmed:
                    e.confirmed_starter = confirmed[e.player_id]
                else:
                    e.confirmed_starter = None
                    e.start_prob = 0.0
                    e.sub_prob = 0.0
            for pid, is_start in confirmed.items():
                if pid not in known:
                    pr = self.player_rates(pid)
                    lineup.append(
                        LineupEntry(pid, pr.name if pr else pid, pr.pos_group if pr else "M", pr.position if pr else None,
                                    1.0 if is_start else 0.0, 0.0 if is_start else 0.3, [], [], ["Takım için yeni oyuncu"], is_start)
                    )
        rates: dict[str, PlayerRates] = {}
        for e in lineup:
            pr = self.player_rates(e.player_id)
            if pr is None:
                p = self.priors.get(e.pos_group, self.priors["M"])
                pr = PlayerRates(e.player_id, e.name, e.pos_group, e.position, p.shots_p90, p.acc, p.conv, 0.0, 0)
            rates[e.player_id] = pr
        return TeamPlayerContext(team_id, lineup, rates, len(recent), lineup_confirmed, len(recent) >= 3, notes)


def own_goal_rate(con: sqlite3.Connection, before: str) -> float:
    """Takım-maç başına rakibin kendi kalesine attığı gol oranı (ω)."""
    row = con.execute(
        """SELECT COALESCE(SUM(pm.own_goals),0) og, COUNT(DISTINCT pm.match_id) nm
           FROM player_match pm JOIN matches m ON m.id=pm.match_id
           WHERE m.completed=1 AND m.summary_status='ok' AND m.date_utc < ?""",
        (before,),
    ).fetchone()
    nm = row["nm"] or 0
    return float(row["og"]) / (2 * nm) if nm > 50 else 0.035


# ---------------------------------------------------------------- kadro gücü (resmi 11 -> takım beklenen golü)

_POS_START_MIN = {"G": 89.0, "D": 84.0, "M": 77.0, "F": 74.0}
LINEUP_ADJ_MIN = 0.85
LINEUP_ADJ_MAX = 1.15


def _start_minutes(e: LineupEntry) -> float:
    return float(np.mean(e.start_exit)) if len(e.start_exit) >= 3 else _POS_START_MIN.get(e.pos_group, 78.0)


def _sub_minutes(e: LineupEntry) -> float:
    return float(np.mean([90 - x for x in e.sub_entry])) if len(e.sub_entry) >= 3 else 20.0


def attack_index(ctx: TeamPlayerContext) -> float:
    """Kadronun beklenen gol katkısı: Σ beklenen dakika/90 × şut/90 × isabet × dönüşüm (oyuncu oranlarından)."""
    tot = 0.0
    for e in ctx.lineup:
        r = ctx.rates.get(e.player_id)
        if r is None:
            continue
        if ctx.lineup_confirmed:
            if e.confirmed_starter is True:
                em = _start_minutes(e)
            elif e.confirmed_starter is False:
                em = max(e.sub_prob, 0.3) * _sub_minutes(e)
            else:
                em = 0.0  # kadroda yok
        else:
            em = e.start_prob * _start_minutes(e) + (1 - e.start_prob) * e.sub_prob * _sub_minutes(e)
        tot += em / 90.0 * r.shots_p90 * r.acc * r.conv
    return tot


def lineup_factor(store: "PlayerStore", team_id: str, confirmed: dict[str, bool], beta: float) -> tuple[float, float]:
    """(çarpan, ham oran): resmi kadronun hücum gücü / olağan (tahmini) kadronun hücum gücü, üssü beta, sınırlı."""
    usual = attack_index(store.team_context(team_id))
    conf = attack_index(store.team_context(team_id, confirmed))
    if usual <= 0 or conf <= 0:
        return 1.0, 1.0
    ratio = conf / usual
    return float(np.clip(ratio**beta, LINEUP_ADJ_MIN, LINEUP_ADJ_MAX)), float(ratio)
