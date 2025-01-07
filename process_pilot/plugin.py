"""Defines the Plugin abstract base class for registering function hooks and strategies."""

from collections.abc import Callable
from subprocess import Popen
from typing import TYPE_CHECKING

from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from process_pilot.process import Process, ProcessStats

LifecycleHookType = Callable[["Process", Popen[str] | None], None]
ReadyStrategyType = Callable[["Process", float], bool]
StatHandlerType = Callable[[list["ProcessStats"]], None]


class Plugin:
    """Abstract base class for plugins."""

    @property
    def name(self) -> str:
        """
        Name of the plugin.

        The name is only used to identify the plugin in logging statements and is not used for any other purpose. The
        base implementation returns the name of the class.

        :returns: The name of the plugin

        """
        return self.__class__.__name__

    def get_lifecycle_hooks(
        self,
    ) -> dict[str, dict[ProcessHookType, list[LifecycleHookType]]]:
        """
        Register custom hooks.

        Each hook is applied to a specific process and process event as described in the README. The
        hooks are tied to a specific process through the name of the lifecycle hook. The hook name
        must match what is provided in the manifest for it to apply to a given process.

        :returns: A nested dictionary mapping the name of the lifecycle hook to process hook types and their functions.
        """
        return {}

    def get_ready_strategies(self) -> dict[str, ReadyStrategyType]:
        """
        Register custom ready strategies.

        These strategies are used to determine if a process is ready to be considered healthy and fully started. When
        a process has dependent processes, the dependency is not considered fulfilled until the ready
        strategy returns True. The strategies are tied to a specific process through the name of the ready strategy. The
        ready strategy name must match what is provided in the manifest for it to apply to a given process.

        :returns: A dictionary mapping strategy names to their corresponding functions.
        """
        return {}

    def get_stats_handlers(self) -> dict[str, list[StatHandlerType]]:
        """
        Register handlers for process statistics.

        These handlers are called periodically to process the statistics of all processes. Each handler
        function is called everytime the statistics are collected from the process. The handlers are
        tied to a specific process through the name of the handler.  The handler name must match what
        is provided in the manifest for it to apply to a given process.

        :returns: A dictionary mapping the name of the stat handler to a list of stat handler functions
        """
        return {}
