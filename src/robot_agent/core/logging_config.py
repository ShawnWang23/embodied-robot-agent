"""Small logging setup shared by executable entry points."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure readable console logs without changing library behavior."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

