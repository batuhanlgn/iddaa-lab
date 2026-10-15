"""Komut satırı işleri.

python -m app.jobs bootstrap   # ilk kurulum: tüm geçmiş + özetler + iddaa + backtest/ayar + tahminler
python -m app.jobs refresh     # güncelleme: yakın dönem veri + iddaa + model + tahmin + kupon sonuçlandırma
python -m app.jobs odds        # yalnızca iddaa oranları + eşleştirme + tahminlerin oran kısmı
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
    progress(f"Kupon sonuçlandırma: {coupons.settle(con)}")


def do_refresh(con, progress: Progress) -> None:
    asyncio.run(ingest_scoreboards(con, progress, months_back=2))
    asyncio.run(ingest_summaries(con, progress))
    _prepare(con, progress)
    _iddaa_safe(con, progress)
    progress(f"Eşleştirme: {match_iddaa_events(con)}")
    progress(f"Kupon sonuçlandırma: {coupons.settle(con)}")
    # Kalibrasyon tahminlerden ÖNCE: yeni tahminler ve kuponlar güncel ağırlıkla hesaplanır
    progress(f"Harman kalibrasyonu: {calibrate_blend(con)}")
    _predict(con, progress)
    gen = coupons.generate(con, days=3, archive=True)
    progress(f"Kuponlar üretildi: {[(k['kind'], len(k['selections'])) for k in gen['coupons']]}")


def do_backtest(con, progress: Progress) -> None:
    from .backtest import evaluate_players, tune_and_evaluate

    _prepare(con, progress)
    res = tune_and_evaluate(con, progress)
    progress(f"Backtest: params={res['params']} aileler={ {k: v.get('validated') for k, v in res['family_validation'].items()} }")
    evaluate_players(con, progress)


def do_bootstrap(con, progress: Progress) -> None:
    asyncio.run(ingest_scoreboards(con, progress))
    asyncio.run(ingest_summaries(con, progress))
    do_backtest(con, progress)
    do_refresh(con, progress)


COMMANDS: dict[str, Callable[[object, Progress], None]] = {
    "bootstrap": do_bootstrap,
    "refresh": do_refresh,
    "odds": do_odds,
    "backtest": do_backtest,
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
