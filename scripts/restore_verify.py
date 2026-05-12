from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_TABLES = ["users", "sessions", "messages", "model_calls", "error_events", "documents"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


def _table_counts(db_url: str, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            for table in tables:
                exists = conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name=:name)"
                    ),
                    {"name": table},
                ).scalar()
                if not exists:
                    counts[table] = -1
                    continue
                value = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                counts[table] = int(value or 0)
    finally:
        engine.dispose()
    return counts


def _wait_db(url: str, *, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except SQLAlchemyError:
            time.sleep(1.0)
    raise RuntimeError("restore-check database did not become ready in time")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup restore verification in isolated temporary PostgreSQL container")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="Source DATABASE_URL (defaults to env)")
    parser.add_argument("--image", default="pgvector/pgvector:pg16", help="Docker image for isolated restore-check database")
    parser.add_argument("--wait-timeout-s", type=int, default=60)
    parser.add_argument("--tables", default=",".join(DEFAULT_TABLES), help="Comma-separated tables to validate counts for")
    args = parser.parse_args()

    source_url = args.database_url.strip()
    if not source_url:
        raise SystemExit("DATABASE_URL is required (pass --database-url or set env)")

    tables = [x.strip() for x in args.tables.split(",") if x.strip()]
    source_counts = _table_counts(source_url, tables)
    print(f"[info] source counts: {source_counts}")

    name = f"vetstudy-restore-check-{secrets.token_hex(4)}"
    port = _free_port()
    restore_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:{port}/restorecheck"

    with tempfile.TemporaryDirectory(prefix="vetstudy-restore-check-") as tmp:
        dump_path = Path(tmp) / "backup.dump"
        _run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--dbname={source_url}", f"--file={dump_path}"])
        try:
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    "POSTGRES_DB=restorecheck",
                    "-e",
                    "POSTGRES_USER=postgres",
                    "-e",
                    "POSTGRES_PASSWORD=postgres",
                    "-p",
                    f"{port}:5432",
                    args.image,
                ]
            )
            _wait_db(restore_url, timeout_s=args.wait_timeout_s)
            _run(["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges", f"--dbname={restore_url}", str(dump_path)])
            restored_counts = _table_counts(restore_url, tables)
            print(f"[info] restored counts: {restored_counts}")
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=False)

    mismatches = []
    for table in tables:
        if source_counts.get(table) != restored_counts.get(table):
            mismatches.append(table)
    if mismatches:
        print(f"[fail] restore verification mismatch for: {', '.join(mismatches)}")
        return 1
    print("[ok] restore verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
