"""Proje genel ayarları. Tüm sabitler burada; kod içinde sihirli sayı tutulmaz."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "iddaa_lab.sqlite3"
TOKEN_PATH = DATA_DIR / ".local_api_token"

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
IDDAA_EVENTS_URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"
IDDAA_COMPETITIONS_URL = "https://sportsbookv2.iddaa.com/sportsbook/competitions?st=1"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) iddaa-lab/1.0 (kisisel analiz)"


@dataclass(frozen=True)
class League:
    slug: str
    name: str
    country: str
    is_cup: bool = False
    detail_months: int = 16  # oyuncu/şut detayının (maç özeti) kaç ay geriye çekileceği


_EXT = 8  # genişletilmiş liglerde detay penceresi (ay)

LEAGUES: tuple[League, ...] = (
    League("tur.1", "Süper Lig", "Türkiye"),
    League("tur.2", "1. Lig", "Türkiye"),
    League("eng.1", "Premier League", "İngiltere"),
    League("eng.2", "Championship", "İngiltere"),
    League("esp.1", "LaLiga", "İspanya"),
    League("ita.1", "Serie A", "İtalya"),
    League("ger.1", "Bundesliga", "Almanya"),
    League("fra.1", "Ligue 1", "Fransa"),
    League("ned.1", "Eredivisie", "Hollanda"),
    League("por.1", "Primeira Liga", "Portekiz"),
    League("bel.1", "Pro League", "Belçika"),
    League("sco.1", "Premiership", "İskoçya"),
    League("uefa.champions", "Şampiyonlar Ligi", "Avrupa", is_cup=True),
    League("uefa.europa", "Avrupa Ligi", "Avrupa", is_cup=True),
    League("uefa.europa.conf", "Konferans Ligi", "Avrupa", is_cup=True),
    # Genişletilmiş kapsam
    League("esp.2", "LaLiga 2", "İspanya", detail_months=_EXT),
    League("ita.2", "Serie B", "İtalya", detail_months=_EXT),
    League("ger.2", "2. Bundesliga", "Almanya", detail_months=_EXT),
    League("fra.2", "Ligue 2", "Fransa", detail_months=_EXT),
    League("eng.3", "League One", "İngiltere", detail_months=_EXT),
    League("eng.4", "League Two", "İngiltere", detail_months=_EXT),
    League("ned.2", "Eerste Divisie", "Hollanda", detail_months=_EXT),
    League("sco.2", "Championship", "İskoçya", detail_months=_EXT),
    League("aut.1", "Bundesliga", "Avusturya", detail_months=_EXT),
    League("sui.1", "Super League", "İsviçre", detail_months=_EXT),
    League("den.1", "Superliga", "Danimarka", detail_months=_EXT),
    League("gre.1", "Super League", "Yunanistan", detail_months=_EXT),
    League("rus.1", "Premier Liga", "Rusya", detail_months=_EXT),
    League("rou.1", "Liga 1", "Romanya", detail_months=_EXT),
    League("swe.1", "Allsvenskan", "İsveç", detail_months=_EXT),
    League("nor.1", "Eliteserien", "Norveç", detail_months=_EXT),
    League("usa.1", "MLS", "ABD", detail_months=_EXT),
    League("bra.1", "Série A", "Brezilya", detail_months=_EXT),
    League("bra.2", "Série B", "Brezilya", detail_months=_EXT),
    League("arg.1", "Liga Profesional", "Arjantin", detail_months=_EXT),
    League("mex.1", "Liga MX", "Meksika", detail_months=_EXT),
    League("col.1", "Primera A", "Kolombiya", detail_months=_EXT),
    League("chi.1", "Primera División", "Şili", detail_months=_EXT),
    League("per.1", "Liga 1", "Peru", detail_months=_EXT),
    League("jpn.1", "J1 League", "Japonya", detail_months=_EXT),
    League("chn.1", "Super League", "Çin", detail_months=_EXT),
    League("ksa.1", "Pro League", "Suudi Arabistan", detail_months=_EXT),
    # Yerel kupalar: alt ve üst ligleri birbirine bağlar
    League("eng.fa", "FA Cup", "İngiltere", is_cup=True, detail_months=_EXT),
    League("eng.league_cup", "Lig Kupası", "İngiltere", is_cup=True, detail_months=_EXT),
    League("esp.copa_del_rey", "Kral Kupası", "İspanya", is_cup=True, detail_months=_EXT),
    League("ita.coppa_italia", "İtalya Kupası", "İtalya", is_cup=True, detail_months=_EXT),
    League("ger.dfb_pokal", "DFB Pokal", "Almanya", is_cup=True, detail_months=_EXT),
)
LEAGUE_BY_SLUG = {lg.slug: lg for lg in LEAGUES}
REFERENCE_LEAGUE = "eng.1"  # hiyerarşik modelde lig ortalamalarının sabitlendiği referans

# Kaç ay geriye veri çekilir (takım skor modeli için). Oyuncu/şut detayları (summary) daha kısa pencere.
HISTORY_MONTHS = 27
SUMMARY_MONTHS = 16

# ESPN nazik istek politikası (sağlayıcı limiti belgelenmemiş -> düşük başla, hata görünce yavaşla)
HTTP_CONCURRENCY = 3
HTTP_MIN_INTERVAL_S = 0.25
HTTP_MAX_RETRIES = 5

# Biten maçlar bitişten sonra bu kadar gün içinde tekrar kontrol edilir (istatistik düzeltmeleri)
RECHECK_DAYS = 3

# Simülasyon
N_SIMS = 10_000
N_SCENARIOS = 3
MAX_GOALS = 10

# Varsayılan model hiperparametreleri; walk-forward ayarlama (tune) sonucu data/model_params.json'a yazılır
DEFAULT_XI = 0.0025  # gün başına zaman sönümü (yarı ömür ~277 gün)
DEFAULT_SIGMA = 0.35  # takım sapması prior std
DEFAULT_TAU = 0.40  # lig ortalaması prior std

# Kupon
BLEND_WEIGHT_DEFAULT = 0.5  # model ağırlığı (geometrik harman); arşiv biriktikçe kalibre edilir
BLEND_MIN_SETTLED = 200  # kalibrasyon için gereken sonuçlanmış iddaa oranlı maç sayısı
VALUE_EV_THRESHOLD = 0.04  # değer seçimi için minimum harmanlı EV
# Kullanıcı tercihi (15 Eki 2026): harman ileriye dönük doğrulanmadan da değer/dengeli kupon üret,
# ama "deneysel" etiketiyle. Doğrulama tamamlanınca etiket kendiliğinden kalkar.
ALLOW_UNVALIDATED_VALUE_COUPONS = True
# Seçim yanlılığına karşı: binlerce aday içinde en yüksek EV'ler çoğunlukla modelin yanıldığı yerlerdir.
# Değer seçimi için model piyasadan en fazla bu kat iyimser olabilir ve oran bu sınırı aşamaz.
VALUE_MAX_MODEL_MARKET_RATIO = 1.35
VALUE_MAX_ODDS = 3.5
VALUE_MIN_ODDS = 1.5
# Kullanıcı tercihi: kuponlar TÜM pazarlardan (ve oyuncu tahminlerinden) seçebilir. Öneriler modelin maça bakışıyla
# uyumlu olmalı: en yüksek EV değil, en olası seçimler (sürpriz/longshot seçimler değer olsa bile önerilmez).
COUPON_MIN_PROB = 0.40       # değer ve dengeli kuponda seçim başına minimum olasılık
PLAYER_PICK_MIN_P = 0.50
PLAYER_PICK_MAX_P = 0.80     # neredeyse kesin (oran < 1.25) seçimler kupona değer katmaz
# Model önerisi kademeleri (modelin maça bakışını yansıtır): net favori -> MS; ağır favori -> handikap;
# favori net değil -> çifte şans; o da yoksa gol pazarları.
PICK_MS_MIN_P = 0.50
PICK_MS_MIN_ODDS = 1.25
PICK_CS_MIN_P = 0.70
PICK_CS_MIN_ODDS = 1.20
PICK_GOALS_MIN_P = 0.55
PICK_GOALS_MIN_ODDS = 1.30
# Tekli ve sistem kuponları
SINGLE_MIN_ODDS = 1.50
SYSTEM_MIN_ODDS = 1.40
# Sürpriz kuponu: yüksek oran, modelin piyasadan belirgin daha fazla inandığı (ama makul) seçimler
SURPRISE_MIN_ODDS = 2.50
SURPRISE_MAX_ODDS = 6.00
SURPRISE_MIN_P = 0.25
SURPRISE_MIN_EDGE = 1.05      # p_model >= 1.05 * p_piyasa
SURPRISE_MAX_EDGE = 1.60      # p_model <= 1.60 * p_piyasa (aşırı ayrışma = model hatası)
SURPRISE_MIN_EV = 0.05
PLAYER_PICK_MIN_START = 0.85
MIN_SELECTION_ODDS = 1.20
