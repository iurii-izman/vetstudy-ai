from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ErrorEvent, Message
from app.db.session import new_session


RISKY_PATTERNS: dict[str, re.Pattern[str]] = {
    "direct_dose_imperative": re.compile(r"\b(дай|дайте|введите|назначь|назначьте)\b.{0,40}\b(доз|мг/кг|mg/kg)\b", re.IGNORECASE),
    "urgent_toxicology_signal": re.compile(r"\b(съел|съела|проглотил|отрав|токсик)\b", re.IGNORECASE),
    "unsafe_certainty": re.compile(r"\b(точно|гарантированно|безопасно)\b.{0,30}\b(лечить|назначать|давать)\b", re.IGNORECASE),
}


def run(*, lookback_hours: int, limit: int, min_hits: int) -> int:
    since = datetime.now(UTC) - timedelta(hours=lookback_hours)
    db = new_session()
    try:
        rows = db.execute(
            select(Message).where(Message.role == "user", Message.created_at >= since).order_by(Message.created_at.desc()).limit(max(1, limit))
        ).scalars().all()
        hits: dict[str, list[str]] = {key: [] for key in RISKY_PATTERNS}
        for msg in rows:
            text = str(msg.content or "")
            for key, pattern in RISKY_PATTERNS.items():
                if pattern.search(text):
                    hits[key].append(text[:240])

        alerts = {k: v for k, v in hits.items() if len(v) >= min_hits}
        if not alerts:
            print("[ok] no new risky phrasing drift patterns detected")
            return 0

        for key, samples in alerts.items():
            db.add(
                ErrorEvent(
                    user_id=None,
                    scope="safety_monitor",
                    category="safety_drift_pattern_detected",
                    details={
                        "pattern": key,
                        "hits": len(samples),
                        "samples": samples[:5],
                        "since": since.isoformat(),
                    },
                )
            )
            print(f"[alert] pattern={key} hits={len(samples)}")
        db.commit()
        return 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Nightly safety drift monitor for risky phrasing patterns")
    p.add_argument("--lookback-hours", type=int, default=24)
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--min-hits", type=int, default=2)
    args = p.parse_args()
    return run(lookback_hours=args.lookback_hours, limit=args.limit, min_hits=args.min_hits)


if __name__ == "__main__":
    sys.exit(main())

