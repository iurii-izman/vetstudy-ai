from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def _mask_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except Exception:
        return url
    if not parsed.netloc or "@" not in parsed.netloc:
        return url
    creds, host = parsed.netloc.rsplit("@", 1)
    if ":" in creds:
        user, _password = creds.split(":", 1)
        netloc = f"{user}:***@{host}"
    else:
        netloc = f"{creds}@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _candidate_urls(database_url: str) -> list[str]:
    candidates = [database_url]
    if "@db:" in database_url:
        candidates.append(database_url.replace("@db:", "@localhost:"))
        candidates.append(database_url.replace("@db:", "@127.0.0.1:"))
    return list(dict.fromkeys(candidates))


def _connect_first(database_url: str):
    errors: list[str] = []
    for candidate in _candidate_urls(database_url):
        engine = create_engine(candidate, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine, candidate, errors
        except SQLAlchemyError as exc:
            errors.append(f"{_mask_url(candidate)} -> {exc.__class__.__name__}: {exc}")
            engine.dispose()
    raise RuntimeError("Could not connect to database using any candidate URL.\n" + "\n".join(errors))


def _sum_value(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show AI cost breakdown from model_calls.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="Database URL. Defaults to DATABASE_URL env.")
    parser.add_argument("--as-json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is required. Pass --database-url or set DATABASE_URL.")

    now_utc = datetime.now(UTC)
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    engine, used_url, connect_errors = _connect_first(args.database_url)
    try:
        with engine.connect() as conn:
            today_total = _sum_value(
                conn.execute(
                    text("SELECT COALESCE(SUM(cost_usd), 0) FROM model_calls WHERE created_at >= :day_start"),
                    {"day_start": day_start},
                ).scalar_one()
            )
            month_total = _sum_value(
                conn.execute(
                    text("SELECT COALESCE(SUM(cost_usd), 0) FROM model_calls WHERE created_at >= :month_start"),
                    {"month_start": month_start},
                ).scalar_one()
            )

            split_rows = conn.execute(
                text(
                    """
                    SELECT
                        CASE WHEN user_id IS NULL THEN 'system_or_scripts' ELSE 'telegram_or_web_user' END AS bucket,
                        COUNT(*) AS calls,
                        COALESCE(SUM(cost_usd), 0) AS cost_usd
                    FROM model_calls
                    WHERE created_at >= :day_start
                    GROUP BY 1
                    ORDER BY cost_usd DESC
                    """
                ),
                {"day_start": day_start},
            ).mappings().all()

            model_rows = conn.execute(
                text(
                    """
                    SELECT provider, model, status, purpose,
                           COUNT(*) AS calls,
                           COALESCE(SUM(input_tokens), 0) AS input_tokens,
                           COALESCE(SUM(output_tokens), 0) AS output_tokens,
                           COALESCE(SUM(cost_usd), 0) AS cost_usd
                    FROM model_calls
                    WHERE created_at >= :day_start
                    GROUP BY provider, model, status, purpose
                    ORDER BY cost_usd DESC, calls DESC
                    """
                ),
                {"day_start": day_start},
            ).mappings().all()
    finally:
        engine.dispose()

    report = {
        "generated_at_utc": now_utc.isoformat(),
        "database_url_used": _mask_url(used_url),
        "database_fallback_applied": used_url != args.database_url,
        "connection_attempt_errors": connect_errors,
        "totals": {
            "today_usd": round(today_total, 6),
            "month_usd": round(month_total, 6),
        },
        "today_user_split": [
            {"bucket": row["bucket"], "calls": int(row["calls"] or 0), "cost_usd": round(_sum_value(row["cost_usd"]), 6)} for row in split_rows
        ],
        "today_model_breakdown": [
            {
                "provider": row["provider"],
                "model": row["model"],
                "status": row["status"],
                "purpose": row["purpose"],
                "calls": int(row["calls"] or 0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "cost_usd": round(_sum_value(row["cost_usd"]), 6),
            }
            for row in model_rows
        ],
    }

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"generated_at_utc: {report['generated_at_utc']}")
    print(f"database_url_used: {report['database_url_used']}")
    print(f"database_fallback_applied: {report['database_fallback_applied']}")
    print(f"today_usd: {report['totals']['today_usd']:.6f}")
    print(f"month_usd: {report['totals']['month_usd']:.6f}")
    print("")
    print("today_user_split:")
    for row in report["today_user_split"]:
        print(f"  - {row['bucket']}: calls={row['calls']} cost_usd={row['cost_usd']:.6f}")
    print("")
    print("today_model_breakdown:")
    for row in report["today_model_breakdown"]:
        print(
            "  - "
            f"{row['provider']}/{row['model']} status={row['status']} purpose={row['purpose']} "
            f"calls={row['calls']} in={row['input_tokens']} out={row['output_tokens']} cost={row['cost_usd']:.6f}"
        )
    if report["connection_attempt_errors"]:
        print("")
        print("connection_attempt_errors:")
        for err in report["connection_attempt_errors"]:
            print(f"  - {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
