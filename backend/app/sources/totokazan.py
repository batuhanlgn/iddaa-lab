"""totokazan.com (anahtarsız, resmi değil): Spor Toto haftalarının oynanma yüzdeleri ("kalabalık") ve iddaa oranı.

GET /api/weeks/       -> data.items[] {id, name, season, week_no, column_price, status open|settled, created_at}
GET /api/weeks/{id}   -> data.week {..., stextra_json{sourceW, kolonOynatildi, dereceler[...]}},
                         data.fixtures[15] {position, home, away, result, score, pct_json{"1","X","2"}, odds_json{...}}

pct_json: oynanma yüzdesi (açık haftada canlı değişir). kolonOynatildi totokazan'ın kendi platformunda oynanan kolon
sayısıdır (resmi toplam değil: 2026/27 9. haftada 1,36 milyon, resmi ikramiye fonu ise ~24 milyon kolona karşılık gelir);
yalnız bilgi olarak saklanır.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Awaitable, Protocol

BASE = "https://totokazan.com/api/weeks"
WEEKS_URL = f"{BASE}/"


class JsonGetter(Protocol):
    def get_json(self, url: str, params: dict[str, str] | None = None) -> Awaitable[Any]: ...


@dataclass
class TkFixture:
    position: int
    home: str
    away: str
    result: str | None                 # "1" | "0" | "2" (totokazan "X" -> "0")
    pct: dict[str, float] | None       # {"1","0","2"} toplamı 1
    odds: dict[str, float] | None      # {"1","0","2"} iddaa oranı (totokazan'ın son okuması)


@dataclass
class TkWeek:
    id: int
    name: str
    status: str                        # open | settled
    column_price: float | None
    created_at: str | None             # TR yerel "YYYY-MM-DD HH:MM:SS"
    source_w: int | None               # webapi.sportoto.gov.tr gameRoundId
    platform_columns: int | None       # kolonOynatildi (totokazan platformu)
    fetched_at: str | None             # totokazan'ın son okuma zamanı
    fixtures: list[TkFixture]


def _out(o: Any) -> str | None:
    s = str(o or "").strip().upper()
    return {"1": "1", "X": "0", "0": "0", "2": "2"}.get(s)


def _triple(d: Any) -> dict[str, float] | None:
    if not isinstance(d, dict):
        return None
    try:
        v = {"1": float(d["1"]), "0": float(d["X"]), "2": float(d["2"])}
    except (KeyError, TypeError, ValueError):
        return None
    return v if all(x > 0 for x in v.values()) else None


def _pct(d: Any) -> dict[str, float] | None:
    v = _triple(d)
    if v is None:
        return None
    s = sum(v.values())
    return {k: x / s for k, x in v.items()} if s > 0 else None


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_list(payload: Any) -> list[dict[str, Any]]:
    items = ((payload or {}).get("data") or {}).get("items") or []
    return [it for it in items if isinstance(it, dict) and it.get("id") is not None]


def parse_week(payload: Any) -> TkWeek | None:
    d = (payload or {}).get("data") or {}
    w = d.get("week")
    if not isinstance(w, dict) or w.get("id") is None:
        return None
    extra = w.get("stextra_json") if isinstance(w.get("stextra_json"), dict) else {}
    fixtures = []
    for f in d.get("fixtures") or []:
        try:
            pos = int(f["position"])
        except (KeyError, TypeError, ValueError):
            continue
        fixtures.append(TkFixture(
            position=pos, home=html.unescape(str(f.get("home") or "")).strip(),
            away=html.unescape(str(f.get("away") or "")).strip(),
            result=_out(f.get("result")), pct=_pct(f.get("pct_json")),
            odds=_triple({k: v for k, v in f["odds_json"].items() if k in ("1", "X", "2")})
            if isinstance(f.get("odds_json"), dict) else None,
        ))
    src_w = _num(extra.get("sourceW"))
    cols = _num(extra.get("kolonOynatildi"))
    return TkWeek(
        id=int(w["id"]), name=str(w.get("name") or ""), status=str(w.get("status") or ""),
        column_price=_num(w.get("column_price")), created_at=w.get("created_at"),
        source_w=int(src_w) if src_w is not None else None, platform_columns=int(cols) if cols else None,
        fetched_at=extra.get("fetchedAt"), fixtures=sorted(fixtures, key=lambda x: x.position),
    )


async def fetch_list(client: JsonGetter) -> list[dict[str, Any]]:
    return parse_list(await client.get_json(WEEKS_URL))


async def fetch_week(client: JsonGetter, week_id: int) -> TkWeek | None:
    return parse_week(await client.get_json(f"{BASE}/{week_id}"))
