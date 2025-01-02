"""Defines the Plugin abstract base class for registering function hooks and strategies."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from subprocess import Popen
from typing import TYPE_CHECKING

from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from process_pilot.process import Process, ProcessStats


class Plugin(ABC):
    """Abstract base class for plugins."""

    @abstractmethod
    def register_hooks(self) -> dict[ProcessHookType, list[Callable[["Process", Popen[str]], None]]]:
        """Register custom hooks."""

    @abstractmethod
    def register_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
        """Register custom ready strategies."""

    @abstractmethod
    def register_stats_handlers(self) -> list[Callable[[list["ProcessStats"]], None]]:
        """Register handlers for process statistics."""
