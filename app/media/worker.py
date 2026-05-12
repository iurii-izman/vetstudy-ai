from __future__ import annotations

import asyncio
import json
import sys
import argparse

from app.media.jobs import worker_diagnostics, worker_loop
from app.observability import configure_logging


async def _run_worker() -> None:
    configure_logging()
    await worker_loop()


async def _run_diagnostics(*, fail_on_stall: bool) -> int:
    try:
        payload = await worker_diagnostics()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": exc.__class__.__name__, "detail": str(exc)}, ensure_ascii=False))
        return 1
    status = "ok"
    pending_count = int(payload.get("pending_count", 0))
    oldest_pending_seconds = float(payload.get("oldest_pending_seconds", 0.0))
    if fail_on_stall and (
        pending_count >= int(payload.get("stall_threshold_pending", 0))
        and oldest_pending_seconds >= float(payload.get("stall_threshold_seconds", 0))
    ):
        status = "stall_detected"
    payload["status"] = status
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if status == "ok" else 2


async def main() -> int:
    parser = argparse.ArgumentParser(description="Media worker process")
    parser.add_argument("--diagnose", action="store_true", help="print worker queue diagnostics and exit")
    parser.add_argument("--fail-on-stall", action="store_true", help="return non-zero if queue stall thresholds are exceeded")
    args = parser.parse_args()

    if args.diagnose:
        return await _run_diagnostics(fail_on_stall=args.fail_on_stall)
    await _run_worker()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
