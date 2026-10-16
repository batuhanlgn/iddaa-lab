"""Spor Toto (anahtarsız): iddaa.com'un kullandığı sportotov2 API'si + canlı uygulama ayarı (kolon bedeli/sınırı).

Kaynaklardaki tarihlerde saat dilimi yok; Türkiye yerel saatidir (UTC+3, yaz saati uygulanmıyor).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .http import FetchError, PoliteClient

SPORTOTO_BASE = "https://sportotov2.iddaa.com"
APPCONFIG_URL = "https://contentv2.iddaa.com/appconfig?platform=WEB"
_TR_OFFSET = timedelta(hours=3)
# dividends[].ordinalNumber -> bilinen maç sayısı (iddaa JS: winnerNumberEnum)
_TIER_BY_ORDINAL = {1: 15, 2: 14, 3: 13, 4: 12}


def tr_to_utc_iso(s: str | None) -> str | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s[:19]) - _TR_OFFSET
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def tr_number(s: Any) -> float | None:
    """Türkçe biçimli sayı: "1.457.880,74" -> 1457880.74"""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except ValueError:
        return None


@dataclass
class TotoEvent:
    event_no: int
    event_name: str
    competition: str
    kickoff_utc: str | None
    result: str | None
    winner: str | None  # "1" | "0" | "2"


@dataclass
class TotoWeek:
    cycle_no: int
    program_name: str | None
    payin_begin_utc: str | None
    payin_end_utc: str
    events: list[TotoEvent]
    dividends: list[dict[str, Any]] | None  # [{tier, winners, amount}]


def parse_week(payload: dict[str, Any]) -> TotoWeek | None:
    if not payload.get("isSuccess") or not payload.get("data"):
        return None
    d = payload["data"]
    events = [
        TotoEvent(
            event_no=int(e["eventNo"]),
            event_name=str(e.get("eventName") or "").strip(),
            competition=str(e.get("competitionName") or ""),
            kickoff_utc=tr_to_utc_iso(e.get("eventDate")),
            result=e.get("result") or None,
            winner=str(e["winner"]) if e.get("winner") not in (None, "") else None,
        )
        for e in d.get("events") or []
    ]
    end = tr_to_utc_iso(d.get("payinEndDate"))
    if not events or end is None:
        return None
    divs = None
    if d.get("dividends"):
        divs = [
            {"tier": _TIER_BY_ORDINAL[int(x["ordinalNumber"])], "winners": int(tr_number(x.get("winners")) or 0),
             "amount": tr_number(x.get("amount")) or 0.0}
            for x in d["dividends"] if int(x.get("ordinalNumber", 0)) in _TIER_BY_ORDINAL
        ]
    return TotoWeek(
        cycle_no=int(d["gameCycleNo"]), program_name=d.get("programName"),
        payin_begin_utc=tr_to_utc_iso(d.get("payinBeginDate")), payin_end_utc=end,
        events=sorted(events, key=lambda e: e.event_no), dividends=divs,
    )


async def fetch_open_week(client: PoliteClient) -> TotoWeek | None:
    return parse_week(await client.get_json(f"{SPORTOTO_BASE}/SporToto"))


async def fetch_result(client: PoliteClient, cycle_no: int) -> TotoWeek | None:
    """Sonuçlanmamış hafta için API `isSuccess:false` (SporTotoNotFound) döner -> None."""
    try:
        return parse_week(await client.get_json(f"{SPORTOTO_BASE}/SporToto/result", {"gameCycleNo": str(cycle_no)}))
    except FetchError as e:
        if e.status in (400, 404):
            return None
        raise


async def fetch_pool_config(client: PoliteClient) -> dict[str, float] | None:
    """Kolon bedeli (TL) ve kupon başına en çok kolon: appconfig.globalConfig.soccerPool."""
    d = await client.get_json(APPCONFIG_URL)
    pool = (((d or {}).get("data") or {}).get("globalConfig") or {}).get("soccerPool") or {}
    price, max_col = pool.get("columnPrice"), pool.get("maxColumn")
    if not price or not max_col:
        return None
    return {"column_price": float(price), "max_column": int(max_col)}
