"""iddaa.com'un kendi web sitesinin kullandığı açık JSON bülteni (ücretsiz, anahtarsız).

Pazar kodları (t, st) gerçek bülten üzerinde oranların tutarlılığı kontrol edilerek çözüldü
(bkz. docs/03_ortak_karar.md). Burada yalnızca modelin fiyatlayabildiği pazarlar tanımlıdır.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import IDDAA_COMPETITIONS_URL, IDDAA_EVENTS_URL
from .http import PoliteClient


@dataclass(frozen=True)
class MarketDef:
    key: str          # iç anahtar (model tarafı bununla eşleşir)
    label: str        # Türkçe pazar adı
    family: str       # doğrulama ailesi: yalnızca o ailenin backtest'te doğrulanan pazarlarıyla aynı bilgiye dayananlar
                      # (ms: sonuç/handikap, iy: İY sonucu ve İY/MS, au: gol sayıları, kg: karşılıklı gol)
    needs_line: bool  # sov (çizgi) gerektirir mi


MARKETS: dict[tuple[int, int], MarketDef] = {
    (1, 1): MarketDef("ms", "Maç Sonucu", "ms", False),
    (2, 92): MarketDef("cs", "Çifte Şans", "ms", False),
    (2, 88): MarketDef("iy", "İlk Yarı Sonucu", "iy", False),
    (2, 36): MarketDef("iy2", "2. Yarı Sonucu", "iy", False),
    (2, 77): MarketDef("iy_cs", "İlk Yarı Çifte Şans", "iy", False),
    (2, 89): MarketDef("kg", "Karşılıklı Gol", "kg", False),
    (2, 720): MarketDef("iy_kg", "İlk Yarı Karşılıklı Gol", "kg", False),  # gol sayısına dayalı -> KG ailesi
    (2, 101): MarketDef("au", "Alt/Üst", "au", True),
    (2, 60): MarketDef("iy_au", "İlk Yarı Alt/Üst", "au", True),  # gol sayısına dayalı -> A/Ü ailesi
    (2, 603): MarketDef("ev_au", "Ev Sahibi Gol Alt/Üst", "au", True),
    (2, 604): MarketDef("dep_au", "Deplasman Gol Alt/Üst", "au", True),
    (2, 100): MarketDef("hnd", "Handikaplı Maç Sonucu", "ms", True),
    (2, 90): MarketDef("iyms", "İlk Yarı / Maç Sonucu", "iy", False),
    (2, 91): MarketDef("tc", "Tek/Çift", "au", False),
    (2, 4): MarketDef("tg", "Toplam Gol Aralığı", "au", False),
    (2, 6): MarketDef("cgy", "Daha Çok Gol Olacak Yarı", "au", False),  # yarı gol sayıları -> A/Ü ailesi
    (2, 7): MarketDef("ms_au", "Maç Sonucu ve Alt/Üst", "ms", True),
    (2, 698): MarketDef("ms_kg", "Maç Sonucu ve Karşılıklı Gol", "ms", False),
    (2, 700): MarketDef("au_kg", "Alt/Üst ve Karşılıklı Gol", "kg", True),
    (2, 48): MarketDef("korner_au", "Korner Alt/Üst", "korner", True),
}


@dataclass
class Outcome:
    no: int
    name: str
    odd: float


@dataclass
class Market:
    t: int
    st: int
    sov: str | None
    mbs: int | None
    outcomes: list[Outcome]

    @property
    def market_key(self) -> str:
        return f"{self.t}:{self.st}:{self.sov or ''}"


@dataclass
class IddaaEvent:
    id: int
    competition_id: int | None
    home_name: str
    away_name: str
    kickoff_utc: str
    mbs: int | None
    is_live: bool
    markets: list[Market]


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_events(payload: dict[str, Any]) -> list[IddaaEvent]:
    """Not: 'il' alanı "canlı bahis sunulacak" bayrağıdır, maçın şu an oynandığını GÖSTERMEZ (type=0 beslemesi
    yalnızca başlamamış maçları içerir). Maç başlamış sayılması başlama saatinden türetilir."""
    if not payload.get("isSuccess"):
        raise ValueError("iddaa bülteni başarısız yanıt döndü")
    now = datetime.now(timezone.utc).timestamp()
    out: list[IddaaEvent] = []
    for e in payload["data"].get("events", []):
        if e.get("sid") != 1 or "d" not in e:
            continue
        markets: list[Market] = []
        for m in e.get("m", []):
            if (m.get("t"), m.get("st")) not in MARKETS:
                continue
            outs = [
                Outcome(no=int(o["no"]), name=str(o.get("n", "")), odd=float(o["odd"]))
                for o in m.get("o", [])
                if o.get("odd") and float(o["odd"]) > 1.0
            ]
            if outs:
                markets.append(Market(int(m["t"]), int(m["st"]), m.get("sov"), m.get("mbc"), outs))
        out.append(
            IddaaEvent(
                id=int(e["i"]),
                competition_id=e.get("ci"),
                home_name=str(e.get("hn", "")).strip(),
                away_name=str(e.get("an", "")).strip(),
                kickoff_utc=_iso(int(e["d"])),
                mbs=e.get("mbc"),
                is_live=int(e["d"]) <= now,
                markets=markets,
            )
        )
    return out


def parse_competitions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload.get("isSuccess"):
        raise ValueError("iddaa yarışma listesi başarısız yanıt döndü")
    rows = []
    for c in payload.get("data", []):
        if str(c.get("si")) != "1":
            continue
        rows.append(
            {"id": int(c["i"]), "name": c.get("n", ""), "country_code": c.get("cid"), "short_name": c.get("sn"), "icon": c.get("ic")}
        )
    return rows


async def fetch_events(client: PoliteClient) -> dict[str, Any]:
    return await client.get_json(IDDAA_EVENTS_URL)


async def fetch_competitions(client: PoliteClient) -> dict[str, Any]:
    return await client.get_json(IDDAA_COMPETITIONS_URL)
