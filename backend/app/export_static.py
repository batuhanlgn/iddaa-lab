"""Statik site için veri dışa aktarımı (GitHub Pages).

python -m app.export_static <çıktı_klasörü>

API'nin döndürdüğü yanıtların AYNISI JSON dosyalarına yazılır; arayüz statik modda bu dosyaları okur.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import api, coupons, db


def _write(out: Path, name: str, data: Any) -> None:
    p = out / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export(out: Path) -> dict[str, int]:
    db.init_db()
    out.mkdir(parents=True, exist_ok=True)
    con = api.con()
    matches = api.matches(days=7, league=None, include_market_only=True)
    _write(out, "matches.json", matches)
    n_detail = 0
    for item in matches["items"]:
        if not item.get("covered"):
            continue
        mid = item["match"]["id"]
        _write(out, f"matches/{mid}.json", api.match_detail(mid))
        n_detail += 1
    _write(out, "coupons.json", coupons.generate(con, days=3, archive=False))
    _write(out, "coupons_history.json", api.coupon_history())
    _write(out, "players_top.json", api.players_top(days=3, limit=300))
    _write(out, "performance.json", api.performance())
    _write(out, "status.json", api.status())
    _write(out, "coverage.json", api.coverage())
    return {"matches": len(matches["items"]), "details": n_detail}


def main() -> int:
    if len(sys.argv) != 2:
        print("Kullanım: python -m app.export_static <çıktı_klasörü>", file=sys.stderr)
        return 2
    res = export(Path(sys.argv[1]).resolve())
    print(f"Dışa aktarıldı: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
