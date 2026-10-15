"""start.ps1 yardımcı: ilk kurulum gerekiyorsa '1', değilse '0' yazdırır."""
from __future__ import annotations

import sqlite3

from .config import DB_PATH


def main() -> None:
    if not DB_PATH.exists():
        print("1")
        return
    con = sqlite3.connect(DB_PATH)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM job_runs WHERE job IN ('bootstrap','refresh') AND status='ok'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    finally:
        con.close()
    print("0" if n else "1")


if __name__ == "__main__":
    main()
