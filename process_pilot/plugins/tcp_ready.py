"""
TCPReadyPlugin class.

The TCPReadyPlugin class which checks if a process is ready by verifying a TCP connection
with the child process.
"""

import socket
import time
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin, ReadyStrategyType

if TYPE_CHECKING:
    from process_pilot.process import Process


class TCPReadyPlugin(Plugin):
    """Plugin that provides TCP-based readiness check strategies."""

    def get_ready_strategies(self) -> dict[str, ReadyStrategyType]:
        """
        Register strategies for the plugin.

        :returns: A dictionary mapping strategy names to their corresponding functions.
        """
        return {
            "tcp": self._wait_tcp_ready,
        }

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
