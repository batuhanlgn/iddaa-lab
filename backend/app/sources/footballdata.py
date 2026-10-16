"""football-data.co.uk (ücretsiz, anahtarsız) tarihsel sonuç + 1X2 oran arşivi: indirme ve sağlam CSV ayrıştırma.

İki dosya ailesi vardır:
- Ana ligler: /mmz4281/{SSSS}/{KOD}.csv — sezon başına bir dosya. Sütunlar: Div, Date, (Time), HomeTeam, AwayTeam,
  FTHG, FTAG, FTR, HTHG, HTAG + bahisçi oranları. 2019/20 öncesi kapanış oranı yalnızca Pinnacle (PSCH...), pazar
  ortalaması açılış tarafında (BbAvH...); sonrası AvgH (açılış) + AvgCH (kapanış ortalaması).
- Ek ligler: /new/{KOD}.csv — tüm sezonlar tek dosyada. Sütunlar: Country, League, Season, Date, Time, Home, Away,
  HG, AG, Res + yalnızca kapanış oranları (PSCH/MaxCH/AvgCH/BFECH/B365CH). İlk yarı skoru yoktur. Son sezonlarda PSCH boş.
Dosyalar UTF-8 BOM'lu ya da cp1252 olabilir; sondaki boş başlıklar ("…,PSCA,,,") ve kısa satırlar görülür.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
import time
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable

import httpx

from ..config import HTTP_MAX_RETRIES, LEAGUE_BY_SLUG, USER_AGENT

log = logging.getLogger(__name__)

FD_BASE = "https://www.football-data.co.uk"
FD_SEASONS = 10              # kaç sezon geriye (içinde bulunulan dahil)
FD_SEASON_START_MONTH = 7    # Temmuz itibarıyla yeni sezon kodu (2026-07 -> "2627")
FD_CONCURRENCY = 2
FD_MIN_INTERVAL_S = 1.0      # küçük, kişisel bir site: istekler arası en az 1 sn

# Kabul edilen toplam ters oran (1 + marj) aralığı: bunun dışı bozuk/yanlış sütun sayılır, sıradaki üçlü denenir
OVERROUND_MIN = 0.98
OVERROUND_MAX = 1.30

Fetcher = Callable[[str], Awaitable[bytes | None]]


@dataclass(frozen=True)
class FdLeague:
    code: str
    slug: str      # ESPN lig kısaltması (config.LEAGUES ile aynı; orada olmayanlar için aynı biçimde)
    name: str
    country: str


FD_MAIN: tuple[FdLeague, ...] = (
    FdLeague("E0", "eng.1", "Premier League", "İngiltere"),
    FdLeague("E1", "eng.2", "Championship", "İngiltere"),
    FdLeague("E2", "eng.3", "League One", "İngiltere"),
    FdLeague("E3", "eng.4", "League Two", "İngiltere"),
    FdLeague("SC0", "sco.1", "Premiership", "İskoçya"),
    FdLeague("SC1", "sco.2", "Championship", "İskoçya"),
    FdLeague("D1", "ger.1", "Bundesliga", "Almanya"),
    FdLeague("D2", "ger.2", "2. Bundesliga", "Almanya"),
    FdLeague("I1", "ita.1", "Serie A", "İtalya"),
    FdLeague("I2", "ita.2", "Serie B", "İtalya"),
    FdLeague("SP1", "esp.1", "LaLiga", "İspanya"),
    FdLeague("SP2", "esp.2", "LaLiga 2", "İspanya"),
    FdLeague("F1", "fra.1", "Ligue 1", "Fransa"),
    FdLeague("F2", "fra.2", "Ligue 2", "Fransa"),
    FdLeague("N1", "ned.1", "Eredivisie", "Hollanda"),
    FdLeague("B1", "bel.1", "Pro League", "Belçika"),
    FdLeague("P1", "por.1", "Primeira Liga", "Portekiz"),
    FdLeague("T1", "tur.1", "Süper Lig", "Türkiye"),
    FdLeague("G1", "gre.1", "Super League", "Yunanistan"),
)
FD_EXTRA: tuple[FdLeague, ...] = (
    FdLeague("ARG", "arg.1", "Liga Profesional", "Arjantin"),
    FdLeague("AUT", "aut.1", "Bundesliga", "Avusturya"),
    FdLeague("BRA", "bra.1", "Série A", "Brezilya"),
    FdLeague("CHN", "chn.1", "Super League", "Çin"),
    FdLeague("DNK", "den.1", "Superliga", "Danimarka"),
    FdLeague("FIN", "fin.1", "Veikkausliiga", "Finlandiya"),
    FdLeague("IRL", "irl.1", "Premier Division", "İrlanda"),
    FdLeague("JPN", "jpn.1", "J1 League", "Japonya"),
    FdLeague("MEX", "mex.1", "Liga MX", "Meksika"),
    FdLeague("NOR", "nor.1", "Eliteserien", "Norveç"),
    FdLeague("POL", "pol.1", "Ekstraklasa", "Polonya"),
    FdLeague("ROU", "rou.1", "Liga 1", "Romanya"),
    FdLeague("RUS", "rus.1", "Premier Liga", "Rusya"),
    FdLeague("SWE", "swe.1", "Allsvenskan", "İsveç"),
    FdLeague("SWZ", "sui.1", "Super League", "İsviçre"),
    FdLeague("USA", "usa.1", "MLS", "ABD"),
)
_FD_BY_SLUG = {lg.slug: lg for lg in FD_MAIN + FD_EXTRA}

# Oran üçlüsü önceliği: kapanış > açılış; pazar ortalaması > Pinnacle > Bet365 > tekil bahisçiler.
# "Max" (en yüksek oran) bilerek yok: farklı bahisçilerden toplandığı için ters toplamı 1'in altına düşebilir.
ODDS_TRIPLES: tuple[tuple[str, str, str, str], ...] = (
    ("AvgC", "AvgCH", "AvgCD", "AvgCA"),
    ("PSC", "PSCH", "PSCD", "PSCA"),
    ("B365C", "B365CH", "B365CD", "B365CA"),
    ("Avg", "AvgH", "AvgD", "AvgA"),
    ("BbAv", "BbAvH", "BbAvD", "BbAvA"),
    ("PS", "PSH", "PSD", "PSA"),
    ("B365", "B365H", "B365D", "B365A"),
    ("WH", "WHH", "WHD", "WHA"),
    ("VC", "VCH", "VCD", "VCA"),
    ("BW", "BWH", "BWD", "BWA"),
    ("IW", "IWH", "IWD", "IWA"),
)


# 2.5 gol Alt/Üst çifti önceliği (scout backtest'inde gol pazarı oranı): kapanış > açılış
OU25_PAIRS: tuple[tuple[str, str], ...] = (
    ("AvgC>2.5", "AvgC<2.5"),
    ("PC>2.5", "PC<2.5"),
    ("B365C>2.5", "B365C<2.5"),
    ("Avg>2.5", "Avg<2.5"),
    ("BbAv>2.5", "BbAv<2.5"),
    ("P>2.5", "P<2.5"),
    ("B365>2.5", "B365<2.5"),
)
OU_OVERROUND_MAX = 1.20


# football-data'nın kısaltılmış/bozuk takım adları -> eşleştirmede kullanılan ad (ESPN ile benzerlik kurulamayanlar)
TEAM_ALIASES: dict[str, str] = {"Buyuksehyr": "Istanbul Basaksehir"}


def canonical_team(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def league_info(slug: str) -> tuple[str, str]:
    """Lig kısaltması -> (ad, ülke). Önce proje lig listesi, sonra football-data tablosu."""
    lg = LEAGUE_BY_SLUG.get(slug)
    if lg is not None:
        return lg.name, lg.country
    fd = _FD_BY_SLUG.get(slug)
    if fd is not None:
        return fd.name, fd.country
    return slug, ""


def season_start_year(today: date) -> int:
    return today.year if today.month >= FD_SEASON_START_MONTH else today.year - 1


def season_code(start_year: int) -> str:
    """2026 -> "2627"."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def main_url(season: str, code: str) -> str:
    return f"{FD_BASE}/mmz4281/{season}/{code}.csv"


def extra_url(code: str) -> str:
    return f"{FD_BASE}/new/{code}.csv"


def decode_csv(raw: bytes) -> str:
    """BOM'u at; UTF-8 dene, olmazsa cp1252, o da olmazsa latin-1 (her baytı kabul eder)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_date(s: str | None) -> str | None:
    """"21/08/2026" | "08/08/15" | "2024-08-16" -> "YYYY-MM-DD". İki haneli yıl 20YY kabul edilir (arşiv 2000 sonrası)."""
    if not s:
        return None
    s = s.strip()
    try:
        if "-" in s:
            y, m, d = (int(x) for x in s[:10].split("-"))
        else:
            d, m, y = (int(x) for x in s.split("/"))
            if y < 100:
                y += 2000
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _int(v: str | None) -> int | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        return int(round(float(v)))
    except ValueError:
        return None


def _odd(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        o = float(v)
    except ValueError:
        return None
    return o if o > 1.0 else None


def pick_odds(row: dict[str, str | None]) -> tuple[str, float, float, float] | None:
    """Öncelik sırasıyla ilk geçerli (üçü de > 1 ve makul marjlı) 1X2 üçlüsü -> (kaynak, o1, ox, o2)."""
    for src, h, d, a in ODDS_TRIPLES:
        o1, ox, o2 = _odd(row.get(h)), _odd(row.get(d)), _odd(row.get(a))
        if o1 is None or ox is None or o2 is None:
            continue
        over = 1.0 / o1 + 1.0 / ox + 1.0 / o2
        if OVERROUND_MIN <= over <= OVERROUND_MAX:
            return src, o1, ox, o2
    return None


def pick_ou25(row: dict[str, str | None]) -> tuple[float, float] | None:
    """İlk geçerli 2.5 gol (Üst, Alt) oran çifti; yoksa None (ek lig dosyalarında bu pazar yok)."""
    for over_col, under_col in OU25_PAIRS:
        ov, un = _odd(row.get(over_col)), _odd(row.get(under_col))
        if ov is None or un is None:
            continue
        if OVERROUND_MIN <= 1.0 / ov + 1.0 / un <= OU_OVERROUND_MAX:
            return ov, un
    return None


@dataclass
class HistMatch:
    league: str
    date: str          # YYYY-MM-DD
    home: str
    away: str
    hg: int
    ag: int
    hthg: int | None
    htag: int | None
    o1: float
    ox: float
    o2: float
    odds_src: str
    o_over25: float | None = None
    o_under25: float | None = None

    @property
    def key(self) -> str:
        return f"{self.league}:{self.date}:{self.home}:{self.away}"


def _first(row: dict[str, str | None], *names: str) -> str | None:
    for n in names:
        v = row.get(n)
        if v is not None and v.strip():
            return v.strip()
    return None


def parse_csv(text: str, league: str, *, min_date: str | None = None) -> list[HistMatch]:
    """Her iki dosya ailesini de ayrıştırır. Skoru ya da geçerli oranı olmayan satırlar (ertelenmiş maç, boş satır)
    atlanır. min_date ("YYYY-MM-DD") verilirse daha eski maçlar alınmaz (ek liglerin tüm sezonlu dosyaları için)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    cols = [h.strip().lstrip("﻿") for h in header]
    out: list[HistMatch] = []
    seen: set[str] = set()
    for raw in reader:
        if not raw or not any(x.strip() for x in raw):
            continue
        row: dict[str, str | None] = {c: (raw[i] if i < len(raw) else None) for i, c in enumerate(cols) if c}
        d = parse_date(row.get("Date"))
        if d is None or (min_date is not None and d < min_date):
            continue
        home = _first(row, "HomeTeam", "Home")
        away = _first(row, "AwayTeam", "Away")
        hg = _int(_first(row, "FTHG", "HG"))
        ag = _int(_first(row, "FTAG", "AG"))
        if not home or not away or hg is None or ag is None:
            continue
        odds = pick_odds(row)
        if odds is None:
            continue
        src, o1, ox, o2 = odds
        hthg, htag = _int(row.get("HTHG")), _int(row.get("HTAG"))
        if hthg is None or htag is None or hthg > hg or htag > ag:
            hthg = htag = None
        ou = pick_ou25(row)
        m = HistMatch(league, d, home, away, hg, ag, hthg, htag, o1, ox, o2, src,
                      ou[0] if ou else None, ou[1] if ou else None)
        if m.key in seen:  # aynı dosyada yinelenen satır
            continue
        seen.add(m.key)
        out.append(m)
    return out


class FdClient:
    """CSV için küçük, nazik HTTP istemcisi (PoliteClient JSON'a özgü). Sınırlı eşzamanlılık, istekler arası
    minimum aralık + jitter, 429/5xx/ağ hatasında üstel geri çekilme. 404 -> None (o sezon/lig dosyası yok)."""

    def __init__(self, concurrency: int = FD_CONCURRENCY, min_interval: float = FD_MIN_INTERVAL_S,
                 timeout: float = 60.0) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._interval = min_interval
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"},
        )
        self.requests = 0

    async def __aenter__(self) -> "FdClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _wait_slot(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval * random.uniform(0.9, 1.3)
        if wait > 0:
            await asyncio.sleep(wait)

    async def get_bytes(self, url: str) -> bytes | None:
        last: str = ""
        for attempt in range(HTTP_MAX_RETRIES):
            async with self._sem:
                await self._wait_slot()
                self.requests += 1
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as e:
                    last = repr(e)
                else:
                    if resp.status_code == 200:
                        body = resp.content
                        if body.lstrip()[:1] == b"<":  # HTML hata/engelleme sayfası, CSV değil
                            raise RuntimeError(f"{url}: CSV yerine HTML döndü")
                        return body
                    if resp.status_code == 404:
                        return None
                    if resp.status_code not in (429, 500, 502, 503, 504):
                        raise RuntimeError(f"{url} -> {resp.status_code}")
                    last = f"HTTP {resp.status_code}"
                    self._interval = min(self._interval * 2.0, 10.0)
            backoff = min(30.0, (2**attempt) * 1.0) * random.uniform(0.8, 1.3)
            log.warning("football-data tekrar denenecek (%s/%s) %s: %s", attempt + 1, HTTP_MAX_RETRIES, url, last)
            await asyncio.sleep(backoff)
        raise RuntimeError(f"{url}: {HTTP_MAX_RETRIES} denemede alınamadı ({last})")
