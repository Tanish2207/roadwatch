"""Wipe every record from the RoadWatch database (schema is preserved).

Deletes rows child-first so the foreign keys declared in ``app/db/models.py``
stay satisfied:

    hazard_status_history  ->  detection_observations  ->  hazards  ->  processing_jobs

Tables, columns and indexes are untouched, so the API starts up empty and
behaves normally — hazards and jobs reappear only when a video is processed
again. Nothing re-seeds the database on startup.

A timestamped backup is written to ``data/database/backups/`` first; pass
``--no-backup`` to skip it.

Usage (from roadwatch/):
    python scripts/clear_database.py
    python scripts/clear_database.py --no-backup
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "database" / "roadwatch.db"
BACKUP_DIR = REPO_ROOT / "data" / "database" / "backups"

# Children before parents (see ondelete rules in app/db/models.py).
TABLES = (
    "hazard_status_history",
    "detection_observations",
    "hazards",
    "processing_jobs",
)


def make_backup(db_path: Path, backup_dir: Path) -> Path:
    """Copy the database aside before it is emptied."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"roadwatch-{stamp}.db"
    shutil.copy2(db_path, target)
    return target


def clear(db_path: Path) -> None:
    """Delete all rows from every data table, then reclaim the space."""
    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        cur = con.cursor()

        existing = {
            r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [t for t in TABLES if t not in existing]
        if missing:
            raise SystemExit(f"! expected table(s) not found: {', '.join(missing)}")

        total = 0
        for table in TABLES:
            before = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            cur.execute(f'DELETE FROM "{table}"')
            total += cur.rowcount
            print(f"  deleted {cur.rowcount:>4} rows from {table:<24} (was {before})")

        # Belt and braces: refuse to report success with rows left behind.
        for table in TABLES:
            left = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if left:
                raise SystemExit(f"! {table} still holds {left} row(s); aborting")

        con.commit()
        print(f"  {total} row(s) deleted; schema unchanged")

        cur.execute("VACUUM")
        con.commit()
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"! could not write to {db_path} ({exc}).\n"
            "  Stop the backend first — it may be holding the database."
        ) from exc
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Empty the RoadWatch database.")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="skip the timestamped backup in data/database/backups/",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"database file to clear (default: {DB_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        raise SystemExit(f"! database not found: {args.db}")

    print(f"database: {args.db}")

    if args.no_backup:
        print("backup:   skipped (--no-backup)")
    else:
        backup = make_backup(args.db, BACKUP_DIR)
        print(f"backup:   {backup}")

    clear(args.db)


if __name__ == "__main__":
    sys.exit(main())
