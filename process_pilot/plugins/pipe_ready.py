"""
PipeReadyPlugin class.

The PipeReadyPlugin class which checks if a process is ready by verifying the existence
of 'ready' in a named pipe.
"""

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from subprocess import Popen
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin
from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from process_pilot.process import Process


class PipeReadyPlugin(Plugin):
    """Plugin that implements a named pipe (FIFO) based readiness check strategy."""

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
            "pipe": self._wait_pipe_ready,
        }

    def _wait_pipe_ready(self, process: "Process", ready_check_interval_secs: float) -> bool:
        """Wait for ready signal via named pipe."""
        if sys.platform == "win32":
            return self._wait_pipe_ready_windows(process, ready_check_interval_secs)
        return self._wait_pipe_ready_unix(process, ready_check_interval_secs)

    def _wait_pipe_ready_windows(self, process: "Process", ready_check_interval_secs: float) -> bool:
        """Windows-specific named pipe implementation."""
        try:
            if sys.platform != "win32":
                error_message = "Windows-specific pipe implementation called on non-Windows platform"
                raise RuntimeError(error_message)

            # Only import on Windows
            import pywintypes
            import win32file
            import win32pipe
        except ImportError:
            error_message = "win32pipe module required for Windows pipe support"
            raise RuntimeError(error_message) from None

        pipe_name = f"\\\\.\\pipe\\{process.name}_ready"
        pipe = None

        try:
            # Create pipe with appropriate security/sharing flags
            pipe = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_INBOUND,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1,
                65536,
                65536,
                0,
                None,
            )

            start_time = time.time()
            while (time.time() - start_time) < process.ready_timeout_sec:
                try:
                    # Wait for client connection
                    win32pipe.ConnectNamedPipe(pipe, None)
                    # Read message
                    result, data = win32file.ReadFile(pipe, 64 * 1024)
                    if result == 0:
                        return data.strip() == "ready"
                except pywintypes.error:
                    time.sleep(ready_check_interval_secs)

            return False

        finally:
            if pipe:
                win32file.CloseHandle(pipe)

    def _wait_pipe_ready_unix(self, process: "Process", ready_check_interval_secs: float) -> bool:
        """Unix-specific FIFO implementation."""
        pipe_path = process.ready_params.get("path")

        if not pipe_path:
            msg = "Path not specified for pipe ready strategy"
            raise RuntimeError(msg)

        pipe_path = Path(pipe_path)

        try:
            start_time = time.time()
            while (time.time() - start_time) < process.ready_timeout_sec:
                try:
                    pipe_file_id = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)
                    with os.fdopen(pipe_file_id) as fifo:
                        data_read = fifo.read()
                        if data_read.strip() == "ready":
                            return True

                        time.sleep(ready_check_interval_secs)
                        continue
                except Exception:  # noqa: BLE001
                    time.sleep(ready_check_interval_secs)
            return False
        finally:
            if pipe_path.exists():
                pipe_path.unlink()
