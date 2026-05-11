from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import ErrorEvent, FeedbackEvent, ProductEvent, ReviewEvent, User


def _run(cmd: list[str]) -> dict:
    done = subprocess.run(cmd, capture_output=True, text=True)
    return {"cmd": " ".join(cmd), "code": done.returncode, "stdout": done.stdout.strip(), "stderr": done.stderr.strip()}


def _database_url_candidates(url: str) -> list[str]:
    candidates = [url]
    if "@db:" in url:
        candidates.append(url.replace("@db:", "@localhost:", 1))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": {},
        "metrics": {},
    }

    if not args.skip_tests:
        report["checks"]["pytest"] = _run(["python", "-m", "pytest", "-q"])
        report["checks"]["ruff"] = _run(["python", "-m", "ruff", "check", ".", "--exclude", "web/node_modules", "--exclude", "web/dist", "--exclude", "artifacts"])

    if args.database_url:
        last_error = None
        for candidate in _database_url_candidates(args.database_url):
            try:
                engine = create_engine(candidate)
                with Session(engine) as db:
                    report["metrics"] = {
                        "users": int(db.execute(select(func.count(User.id))).scalar_one() or 0),
                        "product_events": int(db.execute(select(func.count(ProductEvent.id))).scalar_one() or 0),
                        "negative_feedback_open": int(db.execute(select(func.count(FeedbackEvent.id)).where(FeedbackEvent.feedback_type.in_(["down", "error"]), FeedbackEvent.status.in_(["new", "in_review"]))).scalar_one() or 0),
                        "review_events": int(db.execute(select(func.count(ReviewEvent.id))).scalar_one() or 0),
                        "error_events": int(db.execute(select(func.count(ErrorEvent.id))).scalar_one() or 0),
                    }
                    report["database_url_used"] = candidate
                break
            except Exception as exc:  # pragma: no cover - depends on local DB topology
                last_error = f"{exc.__class__.__name__}: {exc}"
        if not report["metrics"] and last_error:
            report["checks"]["database"] = {"code": 1, "error": last_error}

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
