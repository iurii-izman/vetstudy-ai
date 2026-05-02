from __future__ import annotations

import asyncio

from app.media.jobs import worker_loop
from app.observability import configure_logging


async def main() -> None:
    configure_logging()
    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
