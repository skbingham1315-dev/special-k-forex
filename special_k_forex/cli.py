from __future__ import annotations

import argparse
import logging

from .config import settings
from .engine import ForexEngine
from .logging_utils import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Special K Forex — currency ETF swing trader")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score watchlist and show planned trades without placing any orders.",
    )
    args = parser.parse_args()

    setup_logging()
    settings.validate()

    logger = logging.getLogger(__name__)
    logger.info("Starting Special K Forex")

    engine = ForexEngine(config=settings, dry_run=args.dry_run)
    engine.run()


if __name__ == "__main__":
    main()
