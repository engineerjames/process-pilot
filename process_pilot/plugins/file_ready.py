"""The FileReadyPlugin class which checks if a process is ready by verifying the existence of a file."""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin, ReadyStrategyType

if TYPE_CHECKING:
    from process_pilot.process import Process


class FileReadyPlugin(Plugin):
    """Plugin to check if a process is ready by checking if a file exists."""

    def get_ready_strategies(self) -> dict[str, ReadyStrategyType]:
        """
        Register strategies for the plugin.

        :returns: A dictionary mapping strategy names to their corresponding functions.
        """
        return {
            "file": self._wait_file_ready,
        }

    def _wait_file_ready(self, process: "Process", ready_check_interval_secs: float) -> bool:
        file_path = process.ready_params.get("path")

        if not file_path:
            msg = "Path not specified for file ready strategy"
            raise RuntimeError(msg)

        file_path = Path(file_path)

        start_time = time.time()
        while (time.time() - start_time) < process.ready_timeout_sec:
            if file_path.exists():
                return True
            time.sleep(ready_check_interval_secs)
        return False
