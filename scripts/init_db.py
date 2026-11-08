"""Create sailab_glof.db (if missing) and insert the two seed lakes (if missing). Safe to re-run."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sailab import db  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "sailab_glof.db"


def main() -> None:
    conn = db.connect(DB_PATH)
    ids = db.seed_lakes(conn)
    for row in db.get_lakes(conn):
        print(dict(row))
    conn.close()
    print(f"{DB_PATH}: {len(ids)} seed lakes present")


if __name__ == "__main__":
    main()
