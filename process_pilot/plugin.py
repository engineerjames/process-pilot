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

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Name of the plugin.

        This name must match what is used in the manifest file, as it is what is used
        to tie the plugin to a particular process.

        :returns: The name of the plugin
        """

    @abstractmethod
    def register_hooks(self) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
        """
        Register custom hooks.

        Each hook is applied to a specific process and process event as described in the README. The
        hooks are tied to a specific process through the name of the plugin.

        :returns: A dictionary mapping process hook types to their corresponding functions.
        """

    @abstractmethod
    def register_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
        """
        Register custom ready strategies.

        These strategies are used to determine if a process is ready to be considered healthy. When
        a process has dependent processes, the dependency is not considered fulfilled until the ready
        strategy returns True. The strategies are tied to a specific process through the name of the plugin.

        :returns: A dictionary mapping strategy names to their corresponding functions.
        """

    @abstractmethod
    def register_stats_handlers(self) -> list[Callable[[list["ProcessStats"]], None]]:
        """
        Register handlers for process statistics.

        These handlers are called periodically to process the statistics of all processes. Each handler
        function is called everytime the statistics are collected from the process. The handlers are
        tied to a specific process through the name of the plugin.

        :returns: A list of functions that handle process statistics.
        """
