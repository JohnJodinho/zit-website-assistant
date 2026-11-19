import logging
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import JSONRenderer, TimeStamper
from structlog.stdlib import add_log_level

from app.config import Settings

_git_sha = "local"


def _add_git_sha(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict.setdefault("git_sha", _git_sha)
    return event_dict


def configure_logging(settings: Settings) -> None:
    global _git_sha
    _git_sha = settings.git_sha
    logging.basicConfig(level=settings.log_level, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            TimeStamper(fmt="iso", key="ts"),
            _add_git_sha,
            JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str, settings: Settings | None = None) -> Any:
    fields = {"component": component}
    if settings is not None:
        fields["git_sha"] = settings.git_sha
    return structlog.get_logger(**fields)
