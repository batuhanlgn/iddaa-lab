"""iddaa.com'un kendi web sitesinin kullandığı açık JSON bülteni (ücretsiz, anahtarsız).

Pazar kodları (t, st) gerçek bülten üzerinde oranların tutarlılığı kontrol edilerek çözüldü
(bkz. docs/03_ortak_karar.md). Burada yalnızca modelin fiyatlayabildiği pazarlar tanımlıdır.

Korner ve kart pazarları toplu bültende neredeyse hiç yok; maç detayından (/sportsbook/event/{id}) çekilir
(ingest.ingest_iddaa_details). Pazar adları ve kuralları: /sportsbook/get_market_config (data.m["2_<st>"]).
Kapsam dışı (verimiz yok): ilk yarı korner pazarları (2:49, 2:53, 2:68, 2:864) ve ilk korner (2:56) — ESPN'de devre
bazında korner sayısı yok; oyuncu kart pazarları (794/795/944...) — oyuncu başına kart modeli yok.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import IDDAA_COMPETITIONS_URL, IDDAA_EVENT_DETAIL_URL, IDDAA_EVENTS_URL
from .http import PoliteClient


@dataclass(frozen=True)
class MarketDef:
    key: str          # iç anahtar (model tarafı bununla eşleşir)
    label: str        # Türkçe pazar adı
    family: str       # doğrulama ailesi: yalnızca o ailenin backtest'te doğrulanan pazarlarıyla aynı bilgiye dayananlar
                      # (ms: sonuç/handikap, iy: İY sonucu ve İY/MS, au: gol sayıları, kg: karşılıklı gol,
                      # korner: korner sayıları, kart: iddaa kart sayımı ve kırmızı kart)
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
    # Korner (tam maç, 90 dk). Handikap iki yollu: sov ev sahibinin kornerine eklenir (gol handikabıyla aynı yön).
    (2, 48): MarketDef("korner_au", "Korner Alt/Üst", "korner", True),
    (2, 67): MarketDef("korner_ar", "Toplam Korner Aralığı", "korner", False),
    (2, 822): MarketDef("ev_korner_au", "Ev Sahibi Korner Alt/Üst", "korner", True),
    (2, 823): MarketDef("dep_korner_au", "Deplasman Korner Alt/Üst", "korner", True),
    (2, 52): MarketDef("korner_kdc", "Kim Daha Çok Korner Kullanır", "korner", False),
    (2, 863): MarketDef("korner_hnd", "Korner Handikap", "korner", True),
    # Kart (iddaa sayımı: sarı 1, kırmızı 2; 90 dk)
    (2, 658): MarketDef("kart_au", "Toplam Kart Alt/Üst", "kart", True),
    (2, 865): MarketDef("iy_kart_au", "İlk Yarı Kart Alt/Üst", "kart", True),
    (2, 824): MarketDef("kart_kdc", "Kim Daha Çok Kart Görür", "kart", False),
    (2, 17): MarketDef("kirmizi", "Kırmızı Kart Olur Mu", "kart", False),
}

# Maç detayından çekilen aileler (toplu bültende yok ya da çok seyrek); toplu bülten bu ailelerin oranlarını silmez
DETAIL_FAMILIES = ("korner", "kart")
DETAIL_MARKETS: frozenset[tuple[int, int]] = frozenset(k for k, d in MARKETS.items() if d.family in DETAIL_FAMILIES)
# Tek yönlü sunulabilen pazarlar: iddaa bazen yalnız bir sonucu açar (ör. "Kırmızı Kart Olur Mu"da Hayır 1.00 = kapalı).
# Bu pazarlarda marj arındırılamaz; açık sonucun ham olasılığı (1/oran) piyasa olasılığı sayılır (muhafazakâr).
ONE_SIDED_KEYS = frozenset({"kirmizi"})


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


def _parse_markets(e: dict[str, Any], keys: frozenset[tuple[int, int]] | None = None) -> list[Market]:
    markets: list[Market] = []
    for m in e.get("m", []):
        tk = (m.get("t"), m.get("st"))
        if tk not in MARKETS or (keys is not None and tk not in keys):
            continue
        outs = [
            Outcome(no=int(o["no"]), name=str(o.get("n", "")), odd=float(o["odd"]))
            for o in m.get("o", [])
            if o.get("odd") and float(o["odd"]) > 1.0
        ]
        if outs:
            markets.append(Market(int(m["t"]), int(m["st"]), m.get("sov"), m.get("mbc"), outs))
    return markets


def _event(e: dict[str, Any], now: float, keys: frozenset[tuple[int, int]] | None = None) -> IddaaEvent:
    return IddaaEvent(
        id=int(e["i"]),
        competition_id=e.get("ci"),
        home_name=str(e.get("hn", "")).strip(),
        away_name=str(e.get("an", "")).strip(),
        kickoff_utc=_iso(int(e["d"])),
        mbs=e.get("mbc"),
        is_live=int(e["d"]) <= now,
        markets=_parse_markets(e, keys),
    )


def parse_events(payload: dict[str, Any]) -> list[IddaaEvent]:
    """Not: 'il' alanı "canlı bahis sunulacak" bayrağıdır, maçın şu an oynandığını GÖSTERMEZ (type=0 beslemesi
    yalnızca başlamamış maçları içerir). Maç başlamış sayılması başlama saatinden türetilir."""
    if not payload.get("isSuccess"):
        raise ValueError("iddaa bülteni başarısız yanıt döndü")
    now = datetime.now(timezone.utc).timestamp()
    return [_event(e, now) for e in payload["data"].get("events", []) if e.get("sid") == 1 and "d" in e]


def parse_event_detail(payload: dict[str, Any], event_id: int) -> IddaaEvent | None:
    """Maç detayı (/sportsbook/event/{id}): yalnız detaydan alınan ailelerin (korner, kart) pazarları.
    Yanıt başka bir etkinliğe aitse ya da futbol değilse None."""
    if not payload.get("isSuccess"):
        raise ValueError(f"iddaa maç detayı başarısız yanıt döndü ({event_id})")
    e = payload.get("data")
    if not isinstance(e, dict) or e.get("sid") != 1 or "d" not in e or int(e.get("i", -1)) != event_id:
        return None
    return _event(e, datetime.now(timezone.utc).timestamp(), DETAIL_MARKETS)


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


async def fetch_event_detail(client: PoliteClient, event_id: int) -> dict[str, Any]:
    return await client.get_json(IDDAA_EVENT_DETAIL_URL.format(event_id=event_id))
