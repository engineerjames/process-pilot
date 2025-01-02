"""
TCPReadyPlugin class.

The TCPReadyPlugin class which checks if a process is ready by verifying a TCP connection
with the child process.
"""

import socket
import time
from collections.abc import Callable
from subprocess import Popen
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin
from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from process_pilot.process import Process, ProcessStats


class TCPReadyPlugin(Plugin):
    """Plugin that provides TCP-based readiness check strategies."""

    def register_hooks(self) -> dict[ProcessHookType, list[Callable[["Process", Popen[str]], None]]]:
        """
        Register hooks for the plugin.

        :returns: A dictionary mapping process hook types to their corresponding functions.
        """
        return {}

    def register_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
        """
        Register strategies for the plugin.

        :returns: A dictionary mapping strategy names to their corresponding functions.
        """
        return {
            "tcp": self._wait_tcp_ready,
        }

    def register_stats_handlers(self) -> list[Callable[[list["ProcessStats"]], None]]:
        """Register handlers for process statistics."""
        return []

    def _wait_tcp_ready(self, process: "Process", ready_check_interval_secs: float) -> bool:
        port: int | None = process.ready_params.get("port")
        if not port:
            msg = "Port not specified for TCP ready strategy"
            raise RuntimeError(msg)

        start_time = time.time()
        while (time.time() - start_time) < process.ready_timeout_sec:
            try:
                with socket.create_connection(("localhost", port), timeout=1.0):
                    return True
            except Exception:  # noqa: BLE001
                time.sleep(ready_check_interval_secs)
        return False
