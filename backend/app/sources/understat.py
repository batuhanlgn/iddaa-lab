"""Understat (ücretsiz, anahtarsız) maç başı beklenen gol (xG): indirme ve ayrıştırma.

Erişim biçimi (Ekim 2026'da doğrulandı): site 2026 başında yenilendi; lig sayfası verisini artık
https://understat.com/getLeagueData/{LİG}/{SEZON} JSON ucundan yüklüyor. Yanıt {"teams", "players", "dates"};
"dates" her maç için {id, isResult, h{id,title}, a{id,title}, goals{h,a}, xG{h,a}, datetime} taşır (sayılar metin).
Uç yalnızca sayfanın kendi isteğine benzeyen çağrılara (X-Requested-With + Referer) yanıt verir. Eski biçim (lig
sayfası HTML'inde `datesData = JSON.parse('\\x5B...')`, onaltılık kaçışlı JSON) arşiv kopyaları için de ayrıştırılır.
Sezon = başlangıç yılı (2025 -> 2025/26). Kapsam: 5 büyük lig + Rusya Premier Ligi.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

from ..config import HTTP_MAX_RETRIES, USER_AGENT

log = logging.getLogger(__name__)

US_BASE = "https://understat.com"
US_SOURCE = "understat"
US_CONCURRENCY = 1
US_MIN_INTERVAL_S = 3.0          # resmi olmayan uç: istekler arası en az ~3 sn
US_SEASON_START_MONTH = 7        # Temmuz itibarıyla yeni sezon (RFPL temmuz ortasında başlar)

# ESPN lig kısaltması -> Understat lig adı adayları (sırayla denenir; yeni site boşluklu, eski alt çizgili adlar kullanır)
US_LEAGUES: dict[str, tuple[str, ...]] = {
    "eng.1": ("EPL",),
    "esp.1": ("La_liga", "La liga"),
    "ger.1": ("Bundesliga",),
    "ita.1": ("Serie_A", "Serie A"),
    "fra.1": ("Ligue_1", "Ligue 1"),
    "rus.1": ("RFPL",),
}

# Payload getirici: URL -> çözülmüş JSON (bulunamadıysa None). Testlerde yerel dosyalardan beslenir.
Fetcher = Callable[[str, str], Awaitable[Any | None]]


@dataclass(frozen=True)
class UsMatch:
    us_id: str
    date_utc: str      # "YYYY-MM-DD HH:MM:SS" (Understat zamanı; eşleştirmede ±1 gün tolerans var)
    home: str
    away: str
    hg: int
    ag: int
    xg_home: float
    xg_away: float


def season_start_year(today: date) -> int:
    return today.year if today.month >= US_SEASON_START_MONTH else today.year - 1


def league_data_url(us_league: str, season: int) -> str:
    return f"{US_BASE}/getLeagueData/{quote(us_league)}/{season}"


def league_page_url(us_league: str, season: int) -> str:
    return f"{US_BASE}/league/{quote(us_league)}/{season}"


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x >= 0 else None  # NaN ve negatif değer geçersiz


def _i(v: Any) -> int | None:
    x = _f(v)
    return int(round(x)) if x is not None else None


def parse_dates(dates: list[dict[str, Any]]) -> list[UsMatch]:
    """"dates" listesi -> sonuçlanmış ve xG'si olan maçlar. Eksik/bozuk alanlı satırlar atlanır."""
    out: list[UsMatch] = []
    for d in dates:
        if not isinstance(d, dict) or not d.get("isResult"):
            continue
        h, a = d.get("h") or {}, d.get("a") or {}
        goals, xg = d.get("goals") or {}, d.get("xG") or {}
        hg, ag = _i(goals.get("h")), _i(goals.get("a"))
        xh, xa = _f(xg.get("h")), _f(xg.get("a"))
        home, away, dt = h.get("title"), a.get("title"), d.get("datetime")
        if None in (hg, ag, xh, xa) or not home or not away or not isinstance(dt, str) or len(dt) < 10:
            continue
        out.append(UsMatch(str(d.get("id", "")), dt, str(home), str(away), int(hg), int(ag), float(xh), float(xa)))
    return out


def parse_league_data(payload: Any) -> list[UsMatch]:
    """getLeagueData JSON yanıtı -> maçlar. Beklenen yapı yoksa ValueError (site biçimi değişmiş olabilir)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("dates"), list):
        raise ValueError("Understat yanıtında 'dates' listesi yok")
    return parse_dates(payload["dates"])


_DATES_RE = re.compile(r"datesData\s*=\s*JSON\.parse\('((?:[^'\\]|\\.)*)'\)")


def parse_league_html(html: str) -> list[UsMatch]:
    """Eski lig sayfası HTML'i (arşiv kopyaları): `datesData = JSON.parse('...')` içindeki kaçışlı JSON."""
    m = _DATES_RE.search(html)
    if m is None:
        raise ValueError("Understat sayfasında datesData bulunamadı")
    raw = m.group(1).encode("latin-1", "backslashreplace").decode("unicode_escape")
    # unicode_escape baytları latin-1 sayar: UTF-8 takım adlarını (ör. "Atlético") geri kur
    try:
        raw = raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("datesData liste değil")
    return parse_dates(data)


class UsClient:
    """Understat için küçük, nazik istemci: tek eşzamanlı istek, ~3 sn aralık + jitter, 429/5xx/ağ hatasında üstel
    geri çekilme. 404 -> None. JSON yerine HTML gelirse (engelleme/biçim değişikliği) hata."""

    def __init__(self, concurrency: int = US_CONCURRENCY, min_interval: float = US_MIN_INTERVAL_S,
                 timeout: float = 45.0) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._interval = min_interval
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                         headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/javascript, */*"})
        self.requests = 0

    async def __aenter__(self) -> "UsClient":
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

    async def get_json(self, url: str, referer: str) -> Any | None:
        last = ""
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": referer}
        for attempt in range(HTTP_MAX_RETRIES):
            async with self._sem:
                await self._wait_slot()
                self.requests += 1
                try:
                    resp = await self._client.get(url, headers=headers)
                except httpx.HTTPError as e:
                    last = repr(e)
                else:
                    if resp.status_code == 200:
                        if resp.content.lstrip()[:1] == b"<":
                            raise RuntimeError(f"{url}: JSON yerine HTML döndü")
                        try:
                            return resp.json()
                        except ValueError as e:
                            raise RuntimeError(f"{url}: JSON çözülemedi ({e})") from e
                    if resp.status_code == 404:
                        return None
                    if resp.status_code not in (429, 500, 502, 503, 504):
                        raise RuntimeError(f"{url} -> {resp.status_code}")
                    last = f"HTTP {resp.status_code}"
                    self._interval = min(self._interval * 2.0, 20.0)
            backoff = min(30.0, (2**attempt) * 1.5) * random.uniform(0.8, 1.3)
            log.warning("Understat tekrar denenecek (%s/%s) %s: %s", attempt + 1, HTTP_MAX_RETRIES, url, last)
            await asyncio.sleep(backoff)
        raise RuntimeError(f"{url}: {HTTP_MAX_RETRIES} denemede alınamadı ({last})")


async def fetch_league_season(fetch: Fetcher, slug: str, season: int) -> list[UsMatch] | None:
    """Lig-sezon maçları; lig adı adayları sırayla denenir. Hiçbiri yoksa None (o sezon Understat'te yok)."""
    errors: list[str] = []
    for name in US_LEAGUES[slug]:
        try:
            payload = await fetch(league_data_url(name, season), league_page_url(name, season))
        except RuntimeError as e:
            errors.append(str(e))
            continue
        if payload is None:
            continue
        return parse_league_data(payload)
    if errors:
        raise RuntimeError("; ".join(errors))
    return None


def season_finished(season: int, today: date) -> bool:
    """Sezon (başlangıç yılı) haziran sonunda biter; sonraki sezonun başladığı temmuzdan itibaren bitmiş sayılır."""
    return today >= date(season + 1, US_SEASON_START_MONTH, 1)


def us_datetime(s: str) -> datetime:
    return datetime.fromisoformat(s[:19].replace(" ", "T"))
