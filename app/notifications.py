from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    async def publish(self, message: str) -> None: ...


class SilentNotifier:
    async def publish(self, message: str) -> None:
        return None
