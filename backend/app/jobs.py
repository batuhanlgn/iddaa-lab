"""Komut satırı işleri.

python -m app.jobs bootstrap   # ilk kurulum: tüm geçmiş + özetler + iddaa + backtest/ayar + tahminler
python -m app.jobs refresh     # güncelleme: yakın dönem veri + iddaa + model + tahmin + kupon sonuçlandırma
python -m app.jobs odds        # yalnızca iddaa oranları + eşleştirme + tahminlerin oran kısmı
python -m app.jobs lineups     # saatlik: yaklaşan maçların resmi kadroları + oranlar -> yeniden tahmin ve kupon
python -m app.jobs backtest    # walk-forward doğrulama + hiperparametre ayarı + oyuncu doğrulaması
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback
from typing import Callable

from . import coupons, db
from .blend import calibrate_blend
from .ingest import backfill_periods, ingest_iddaa, ingest_scoreboards, ingest_summaries, iso, repair_missing_stats, utcnow
from .matching import match_iddaa_events
from .tracking import update_tracking

log = logging.getLogger("jobs")
Progress = Callable[[str], None]


def _progress_factory(con, run_id: int) -> Progress:
    def progress(msg: str) -> None:
        log.info(msg)
        con.execute("UPDATE job_runs SET message=? WHERE id=?", (msg, run_id))

    return progress


def run_job(name: str, fn: Callable[[object, Progress], object]) -> int:
    db.init_db()
    con = db.connect()
    cur = con.execute("INSERT INTO job_runs(job, started_at, status) VALUES(?,?,?)", (name, iso(utcnow()), "running"))
    run_id = int(cur.lastrowid or 0)
    progress = _progress_factory(con, run_id)
    try:
        fn(con, progress)
    except Exception as e:  # noqa: BLE001 - iş kaydına yazılır, çıkış kodu 1
        con.execute(
            "UPDATE job_runs SET status='error', finished_at=?, message=? WHERE id=?",
            (iso(utcnow()), f"{type(e).__name__}: {e}", run_id),
        )
        traceback.print_exc()
        return 1
    con.execute("UPDATE job_runs SET status='ok', finished_at=? WHERE id=?", (iso(utcnow()), run_id))
    return 0


def _predict(con, progress: Progress) -> None:
    from .model.pipeline import fit_all, predict_upcoming

    progress("Modeller eğitiliyor (gol, şut, korner, oyuncu)…")
    fm = fit_all(con)
    progress(f"Model {fm.version}: {fm.goals.n_matches} maç, rho={fm.goals.rho:.3f}. Tahminler hesaplanıyor…")
    res = predict_upcoming(con, fm, days=7, progress=progress)
    progress(f"Tahminler: {res}")


def _prepare(con, progress: Progress) -> None:
    """İdempotent veri hazırlığı: eksik istatistik onarımı + İY/90 dk skorları (eğitim bunlara dayanır)."""
    progress(f"Eksik istatistik onarımı: {repair_missing_stats(con)} maç")
    progress(f"Devre skorları (İY / 90 dk): {backfill_periods(con)} maç")
    from .model.pipeline import compact_predictions

    progress(f"Tahmin arşivi sıkıştırma: {compact_predictions(con)} kayıt günlüğe aktarıldı")
    progress(f"Mükerrer kupon temizliği: {coupons.dedupe_daily_coupons(con)} kayıt")


def _finish_cycle(con, progress: Progress) -> None:
    from .live_picks import record_live_picks, settle_live_picks

    try:
        progress(f"Canlı öneriler: {record_live_picks(con)} · sonuçlandırma {settle_live_picks(con)}")
    except Exception as e:  # noqa: BLE001 - canlı kaynak hatası ana güncellemeyi durdurmasın
        log.exception("Canlı öneri kaydı başarısız")
        progress(f"UYARI: canlı öneriler kaydedilemedi ({type(e).__name__}: {e})")
    try:
        from .sportoto import ingest_toto

        asyncio.run(ingest_toto(con, progress))
    except Exception as e:  # noqa: BLE001 - Spor Toto kaynağı hatası ana güncellemeyi durdurmasın
        log.exception("Spor Toto güncellenemedi")
        progress(f"UYARI: Spor Toto güncellenemedi ({type(e).__name__}: {e})")
    progress(f"Kupon sonuçlandırma: {coupons.settle(con)}")
    progress(f"Öneri/CLV takibi: {update_tracking(con)}")
    gen = coupons.generate(con, days=3, archive=True)
    progress(f"Kuponlar üretildi: {[(k['kind'], len(k['selections'])) for k in gen['coupons']]}")


def _iddaa_safe(con, progress: Progress) -> None:
    """iddaa erişilemezse (ör. yurt dışı IP engeli) iş çökmesin: eski oranlar pasifleşmez, tahminler yine üretilir."""
    try:
        asyncio.run(ingest_iddaa(con, progress))
    except Exception as e:  # noqa: BLE001 - kaynak hatası iş kaydına yazılır, diğer adımlar sürer
        log.exception("iddaa bülteni alınamadı")
        progress(f"UYARI: iddaa bülteni alınamadı ({type(e).__name__}: {e}); oranlar güncellenmedi")


def do_odds(con, progress: Progress) -> None:
    _prepare(con, progress)
    _iddaa_safe(con, progress)
    progress(f"Eşleştirme: {match_iddaa_events(con)}")
    _predict(con, progress)
    _finish_cycle(con, progress)


def do_lineups(con, progress: Progress) -> None:
    """Saatlik: yaklaşan maçların (36 saat) özetlerinden resmi kadrolar + güncel oranlar -> yeniden tahmin ve kupon."""
    _prepare(con, progress)
    asyncio.run(ingest_summaries(con, progress, pre_only=True))
    _standings_safe(con, progress)
    _iddaa_safe(con, progress)
    progress(f"Eşleştirme: {match_iddaa_events(con)}")
    _predict(con, progress)
    _finish_cycle(con, progress)


def _standings_safe(con, progress: Progress) -> None:
    """15 dakikalık işte yalnız puan durumu (~50 istek): maç günü tablo güncel kalsın."""
    from .league_info import ingest_standings

    try:
        asyncio.run(ingest_standings(con, progress))
    except Exception as e:  # noqa: BLE001 - görüntüleme verisi; ana işi durdurmaz
        log.exception("Puan durumu başarısız")
        progress(f"UYARI: puan durumu alınamadı ({type(e).__name__}: {e})")


def _league_info_safe(con, progress: Progress) -> None:
    """Puan durumu + karşılıklı geçmiş: yalnız görüntüleme verisi; hata ana güncellemeyi durdurmaz."""
    from .league_info import ingest_h2h, ingest_standings

    for step in (ingest_standings, ingest_h2h):
        try:
            asyncio.run(step(con, progress))
        except Exception as e:  # noqa: BLE001 - kaynak hatası iş kaydına yazılır, diğer adımlar sürer
            log.exception("%s başarısız", step.__name__)
            progress(f"UYARI: {step.__name__} tamamlanamadı ({type(e).__name__}: {e})")


def do_refresh(con, progress: Progress) -> None:
    asyncio.run(ingest_scoreboards(con, progress, months_back=2))
    asyncio.run(ingest_summaries(con, progress))
    _league_info_safe(con, progress)
    _prepare(con, progress)
    _iddaa_safe(con, progress)
    progress(f"Eşleştirme: {match_iddaa_events(con)}")
    # Kalibrasyon tahminlerden ÖNCE: yeni tahminler ve kuponlar güncel ağırlıkla hesaplanır
    progress(f"Harman kalibrasyonu: {calibrate_blend(con)}")
    _predict(con, progress)
    _finish_cycle(con, progress)


def do_backtest(con, progress: Progress) -> None:
    from .backtest import evaluate_players, tune_and_evaluate

    _prepare(con, progress)
    res = tune_and_evaluate(con, progress)
    progress(f"Backtest: params={res['params']} aileler={ {k: v.get('validated') for k, v in res['family_validation'].items()} }")
    evaluate_players(con, progress)
    from .backtest import tune_lineup_beta

    tune_lineup_beta(con, progress)


def do_bootstrap(con, progress: Progress) -> None:
    asyncio.run(ingest_scoreboards(con, progress))
    asyncio.run(ingest_summaries(con, progress))
    do_backtest(con, progress)
    do_refresh(con, progress)


COMMANDS: dict[str, Callable[[object, Progress], None]] = {
    "bootstrap": do_bootstrap,
    "refresh": do_refresh,
    "odds": do_odds,
    "lineups": do_lineups,
    "lineup_beta": lambda con, pr: __import__("app.backtest", fromlist=["tune_lineup_beta"]).tune_lineup_beta(con, pr) and None,
    "backtest": do_backtest,
    "league_info": _league_info_safe,
    "ingest": lambda con, pr: (asyncio.run(ingest_scoreboards(con, pr)), asyncio.run(ingest_summaries(con, pr)),
                               asyncio.run(ingest_iddaa(con, pr))) and None,
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="app.jobs")
    p.add_argument("command", choices=sorted(COMMANDS))
    args = p.parse_args(argv)
    return run_job(args.command, COMMANDS[args.command])


if __name__ == "__main__":
    sys.exit(main())
