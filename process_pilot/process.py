"""Main classes and definitions for ProcessPilot."""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from time import sleep
from typing import Any, Literal, cast

import psutil
import yaml
from pydantic import BaseModel, Field, model_validator

ShutdownStrategy = Literal["restart", "do_not_restart", "shutdown_everything"]
ProcessHookType = Literal["pre_start", "post_start", "on_shutdown", "on_restart"]
ReadyStrategy = Literal["tcp", "pipe", "file"]


class ProcessRuntimeInfo:
    """Contains process-related runtime information."""

    def __init__(self) -> None:
        """Construct a ProcessRuntimeInfo instance."""
        self._memory_usage_mb = 0.0
        self._cpu_usage_percent = 0.0
        self._max_memory_usage_mb = 0.0
        self._max_cpu_usage = 0.0

    @property
    def memory_usage_mb(self) -> float:
        """Return the current memory usage in megabytes."""
        return self._memory_usage_mb

    @memory_usage_mb.setter
    def memory_usage_mb(self, value: float) -> None:
        self._memory_usage_mb = value
        self._max_memory_usage_mb = max(value, self._max_memory_usage_mb)

    @property
    def cpu_usage_percent(self) -> float:
        """Return the current CPU utilization as a percentage."""
        return self._cpu_usage_percent

    @cpu_usage_percent.setter
    def cpu_usage_percent(self, value: float) -> None:
        self._cpu_usage_percent = value
        self._max_cpu_usage = max(value, self._max_cpu_usage)

    @property
    def max_memory_usage_mb(self) -> float:
        """Return the maximum memory usage in megabytes."""
        return self._max_memory_usage_mb

    @property
    def max_cpu_usage(self) -> float:
        """Return the maximum CPU usage (as a %)."""
        return self._max_cpu_usage


class Process(BaseModel):
    """Pydantic model of an individual process that is being managed."""

    name: str
    """The name of the process."""

    path: Path
    """The path to the executable that will be run."""

    args: list[str] = Field(default=[])
    """The arguments to pass to the executable when it is run."""

    env: dict[str, str] = Field(default_factory=dict)
    """Environment variables to pass to the process. These are merged with the parent process environment."""

    timeout: float | None = None
    """The amount of time to wait for the process to exit before forcibly killing it."""

    shutdown_strategy: ShutdownStrategy | None = "restart"
    """The strategy to use when the process exits.  If not specified, the default is to restart the process."""

    dependencies: list[str] | list["Process"] = Field(default=[])
    """
    A list of dependencies that must be started before this process can be started.
    This is a list of other names in the manifest.
    """

    hooks: dict[ProcessHookType, list[Callable[["Process"], None]]] = Field(default={})
    """A series of functions to call at various points in the process lifecycle."""

    _runtime_info: ProcessRuntimeInfo = ProcessRuntimeInfo()
    """Runtime information about the process"""

    ready_strategy: ReadyStrategy | None = None
    """Optional strategy to determine if the process is ready"""

    ready_timeout_sec: float = 10.0
    """The amount of time to wait for the process to signal readiness before giving up"""

    ready_params: dict[str, Any] = Field(default_factory=dict)
    """Additional parameters for the ready strategy"""

    @property
    def command(self) -> list[str]:
        """
        Return the path to the executable along with all arguments.

        :returns: A combined list of strings that contains both the executable path and all arguments
        """
        return [str(self.path), *self.args]

    def register_hook(
        self,
        hook_type: ProcessHookType,
        callback: Callable[["Process"], None] | list[Callable[["Process"], None]],
    ) -> None:
        """
        Register a callback for a particular process.

        :param hook_type: The type of hook to register the callback for
        :param callback: The function to call or a list of functions to call
        """
        if hook_type not in ("pre_start", "post_start", "on_shutdown", "on_restart"):
            error_message = f"Invalid hook type provided: {hook_type}"
            raise ValueError(error_message)

        if hook_type not in self.hooks:
            self.hooks[hook_type] = []

        if isinstance(callback, list):
            self.hooks[hook_type].extend(callback)
        else:
            self.hooks[hook_type].append(callback)

    def record_process_stats(self, pid: int) -> None:
        """Get the memory usage of a process by its PID."""
        try:
            found_process = psutil.Process(pid)
            memory_usage = found_process.memory_info()
            cpu_usage = found_process.cpu_percent()
        except psutil.NoSuchProcess:
            logging.exception("Unable to find process to get stats for with PID %i", pid)
            return
        else:
            self._runtime_info.cpu_usage_percent = cpu_usage
            self._runtime_info.memory_usage_mb = memory_usage.rss / (1024 * 1024)

    def wait_until_ready(self, pid: int, ready_check_interval_secs: float) -> bool:
        """Wait for process to signal readiness."""
        logging.debug("Waiting for process %s to signal ready with pid %i", self.name, pid)

        if self.ready_strategy == "tcp":
            return self._wait_tcp_ready(ready_check_interval_secs)

        if self.ready_strategy == "pipe":
            return self._wait_pipe_ready(ready_check_interval_secs)

        if self.ready_strategy == "file":
            return self._wait_file_ready(ready_check_interval_secs)

        return True

    def _wait_tcp_ready(self, ready_check_interval_secs: float) -> bool:
        """Wait for TCP port to be listening."""
        port: int | None = self.ready_params.get("port")

        if not port:
            error_message = "Port not specified for TCP ready strategy"
            raise RuntimeError(error_message)

        start_time = time.time()

        while (time.time() - start_time) < self.ready_timeout_sec:
            try:
                with socket.create_connection(("localhost", port), timeout=1.0):
                    return True
            except Exception:  # noqa: BLE001
                time.sleep(ready_check_interval_secs)
        return False

    def _wait_pipe_ready(self, ready_check_interval_secs: float) -> bool:
        """Wait for ready signal via named pipe."""
        if sys.platform == "win32":
            return self._wait_pipe_ready_windows(ready_check_interval_secs)
        return self._wait_pipe_ready_unix(ready_check_interval_secs)

    def _wait_pipe_ready_windows(self, ready_check_interval_secs: float) -> bool:
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

        pipe_name = f"\\\\.\\pipe\\{self.name}_ready"
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
            while (time.time() - start_time) < self.ready_timeout_sec:
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

    def _wait_pipe_ready_unix(self, ready_check_interval_secs: float) -> bool:
        """Unix-specific FIFO implementation."""
        pipe_path = self.ready_params.get("path")

        if not pipe_path:
            msg = "Path not specified for pipe ready strategy"
            raise RuntimeError(msg)

        pipe_path = Path(pipe_path)

        if not pipe_path.exists():
            os.mkfifo(pipe_path)

        try:
            start_time = time.time()
            while (time.time() - start_time) < self.ready_timeout_sec:
                try:
                    with Path.open(pipe_path) as fifo:
                        return fifo.read().strip() == "ready"
                except Exception:  # noqa: BLE001
                    time.sleep(ready_check_interval_secs)
            return False
        finally:
            if pipe_path.exists():
                pipe_path.unlink()

    def _wait_file_ready(self, ready_check_interval_secs: float) -> bool:
        """Wait for ready signal via presence of a file."""
        if "path" not in self.ready_params or not isinstance(self.ready_params["path"], str):
            error_message = "Path not specified for file ready strategy or not a string"
            raise RuntimeError(error_message)

        file_path = Path(self.ready_params.get("path", ""))

        # TODO: How do we ensure that clients delete the file?

        if not file_path:
            error_message = "Path not specified for file ready strategy"
            raise RuntimeError(error_message)

        start_time = time.time()
        while (time.time() - start_time) < self.ready_timeout_sec:
            if file_path.exists():
                return True
            time.sleep(ready_check_interval_secs)

        return False


class ProcessManifest(BaseModel):
    """Pydantic model of each process that is being managed."""

    processes: list[Process]

    _manifest_path: Path | None = None

    @model_validator(mode="after")
    def resolve_dependencies(self) -> "ProcessManifest":
        """
        Resolve dependencies for each process in the manifest.

        :returns: The updated manifest with resolved dependencies
        """
        process_dict = {process.name: process for process in self.processes}

        process_name_set: set[str] = set()

        for process in self.processes:
            resolved_dependencies = []

            # Ensure no duplicate names in the manifest
            if process.name in process_name_set:
                error_message = f"Duplicate process name found: '{process.name}'"
                raise ValueError(error_message)

            process_name_set.add(process.name)

            for dep_name in process.dependencies:
                if dep_name in process_dict and isinstance(dep_name, str):
                    resolved_dependencies.append(process_dict[dep_name])
                else:
                    error_message = f"Dependency '{dep_name}' for process '{process.name}' not found."
                    raise ValueError(error_message)

            process.dependencies = resolved_dependencies

        return self

    @model_validator(mode="after")
    def order_dependencies(self) -> "ProcessManifest":
        """
        Orders the process list based on the dependencies of each process.

        :returns: The updated manifest with ordered dependencies
        :raises: ValueError if circular dependencies are detected
        """
        ordered_processes = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(process: Process) -> None:
            if process.name in visited:
                return

            if process.name in visiting:
                error_message = (
                    f"Circular dependency detected involving process {process.name} and process {list(visiting)[-1]}"
                )
                raise ValueError(error_message)

            visiting.add(process.name)
            process.dependencies = cast(list[Process], process.dependencies)

            for dep in process.dependencies:
                visit(dep)

            visiting.remove(process.name)
            visited.add(process.name)

            ordered_processes.append(process)

        for process in self.processes:
            visit(process)

        self.processes = ordered_processes
        return self

    @model_validator(mode="after")
    def validate_ready_config(self) -> "ProcessManifest":
        """Validate the ready strategy configuration."""
        for p in self.processes:
            if p.ready_strategy is None:
                continue

            if p.ready_strategy in ("file", "pipe") and "path" not in p.ready_params:
                error_message = f"File and pipe ready strategies require 'path' parameter: {p.name}"
                raise ValueError(error_message)

            if p.ready_strategy == "tcp" and "port" not in p.ready_params:
                error_message = f"TCP ready strategy requires 'port' parameter: {p.name}"
                raise ValueError(error_message)

        return self

    def _resolve_paths_relative_to_manifest(self, manifest_path: Path) -> None:
        """Resolve relative paths in the manifest to be relative to the manifest file."""
        manifest_dir = manifest_path.parent

        for process in self.processes:
            if not process.path.is_absolute() and str(process.path) not in ("python, sleep"):
                process.path = manifest_dir / process.path

            # Check and resolve paths in arguments
            resolved_args = []
            for arg in process.args:
                arg_path = Path(arg)
                if arg_path.suffix and not arg_path.is_absolute():  # Check if the argument has a file extension
                    arg_path = manifest_dir / arg_path
                resolved_args.append(str(arg_path) if arg_path.suffix else arg)
            process.args = resolved_args

    @classmethod
    def from_json(cls, path: Path) -> "ProcessManifest":
        """
        Load a JSON formatted process manifest.

        :param path: Path to the JSON file
        """
        with path.open("r") as f:
            json_data = json.loads(f.read())

        instance = cls(**json_data)

        instance._resolve_paths_relative_to_manifest(path)  # noqa: SLF001

        return instance

    @classmethod
    def from_yaml(cls, path: Path) -> "ProcessManifest":
        """
        Load a YAML formatted process manifest.

        :param path: Path to the YAML file
        """
        with path.open("r") as f:
            yaml_data = yaml.safe_load(f)

        instance = cls(**yaml_data)

        instance._resolve_paths_relative_to_manifest(path)  # noqa: SLF001

        return instance


class ProcessPilot:
    """Class that manages a manifest-driven set of processes."""

    def __init__(
        self,
        manifest: ProcessManifest,
        process_poll_interval: float = 0.1,
        ready_check_interval: float = 0.1,
    ) -> None:
        """
        Construct the ProcessPilot class.

        :param manifest: Manifest that contains a definition for each process
        :param poll_interval: The amount of time to wait in-between service checks in seconds
        :param ready_check_interval: The amount of time to wait in-between readiness checks in seconds
        """
        self._manifest = manifest
        self._process_poll_interval_secs = process_poll_interval
        self._ready_check_interval_secs = ready_check_interval
        self._running_processes: list[tuple[Process, subprocess.Popen[str]]] = []
        self._shutting_down: bool = False

        self._thread = threading.Thread(target=self._run)

        # Configure the logger
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

    def _run(self) -> None:
        try:
            self._initialize_processes()

            logging.debug("Entering main execution loop")
            while not self._shutting_down:
                self._process_loop()

                sleep(self._process_poll_interval_secs)

                if not self._running_processes:
                    logging.warning("No running processes to manage--shutting down.")
                    self.stop()

        except KeyboardInterrupt:
            logging.warning("Detected keyboard interrupt--shutting down.")
            self.stop()

    def start(self) -> None:
        """Start all services."""
        if self._thread.is_alive():
            error_message = "ProcessPilot is already running"
            raise RuntimeError(error_message)

        if len(self._manifest.processes) == 0:
            error_message = "No processes to start"
            raise RuntimeError(error_message)

        self._shutting_down = False
        self._thread.start()

    def _initialize_processes(self) -> None:
        """Initialize all processes and wait for ready signals."""
        for entry in self._manifest.processes:
            logging.debug(
                "Executing command: %s",
                entry.command,
            )

            # Merge environment variables
            process_env = os.environ.copy()
            process_env.update(entry.env)

            ProcessPilot._execute_hooks(entry, "pre_start")
            new_popen_result = subprocess.Popen(  # noqa: S603
                entry.command,
                encoding="utf-8",
                env=process_env,
            )

            if entry.ready_strategy:
                if entry.wait_until_ready(new_popen_result.pid, self._ready_check_interval_secs):
                    logging.debug("Process %s signaled ready", entry.name)
                else:
                    error_message = f"Process {entry.name} failed to signal ready"
                    raise RuntimeError(error_message)  # TODO: Should we handle this differently?
            else:
                logging.debug("No ready strategy for process %s", entry.name)

            ProcessPilot._execute_hooks(entry, "post_start")
            self._running_processes.append((entry, new_popen_result))

    @staticmethod
    def _execute_hooks(process: Process, hook_type: ProcessHookType) -> None:
        if hook_type not in process.hooks or len(process.hooks[hook_type]) == 0:
            logging.warning("No %s hooks available for process: '%s'", hook_type, process.name)
            return

        logging.debug("Executing hooks for process: '%s'", process.name)
        for hook in process.hooks[hook_type]:
            hook(process)

    def _process_loop(self) -> None:
        processes_to_remove: list[Process] = []
        processes_to_add: list[tuple[Process, subprocess.Popen[str]]] = []

        for process_entry, process in self._running_processes:
            result = process.poll()

            # Process has not exited yet
            if result is None:
                process_entry.record_process_stats(process.pid)
                continue

            processes_to_remove.append(process_entry)

            ProcessPilot._execute_hooks(process_entry, "on_shutdown")

            match process_entry.shutdown_strategy:
                case "shutdown_everything":
                    logging.warning(
                        "%s shutdown with return code %i - shutting down everything.",
                        process_entry,
                        process.returncode,
                    )
                    self.stop()
                case "do_not_restart":
                    logging.warning(
                        "%s shutdown with return code %i.",
                        process_entry,
                        process.returncode,
                    )
                case "restart":
                    logging.warning(
                        "%s shutdown with return code %i.  Restarting...",
                        process_entry,
                        process.returncode,
                    )

                    logging.debug(
                        "Running command %s",
                        process_entry.command,
                    )

                    processes_to_add.append(
                        (
                            process_entry,
                            subprocess.Popen(  # noqa: S603
                                process_entry.command,
                                encoding="utf-8",
                                env={**os.environ, **process_entry.env},
                            ),
                        ),
                    )

                    ProcessPilot._execute_hooks(process_entry, "on_restart")
                case _:
                    logging.error(
                        "Shutdown strategy not handled: %s",
                        process_entry.shutdown_strategy,
                    )

        self._remove_processes(processes_to_remove)
        self._running_processes.extend(processes_to_add)

    def _remove_processes(self, processes_to_remove: list[Process]) -> None:
        for p in processes_to_remove:
            processes_to_investigate = [(proc, popen) for (proc, popen) in self._running_processes if proc == p]

            for proc_to_inv in processes_to_investigate:
                _, popen_obj = proc_to_inv
                if popen_obj.returncode is not None:
                    logging.debug(
                        "Removing process with output: %s",
                        popen_obj.communicate(),
                    )
                    self._running_processes.remove(proc_to_inv)

    def stop(self) -> None:
        """Stop all services."""
        self._shutting_down = True

        self._thread.join()

        for process_entry, process in self._running_processes:
            process.terminate()

            try:
                process.wait(process_entry.timeout)
            except subprocess.TimeoutExpired:
                logging.warning(
                    "Detected timeout for %s: forceably killing.",
                    process_entry,
                )
                process.kill()


if __name__ == "__main__":
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "tests" / "examples" / "services.json")
    pilot = ProcessPilot(manifest)

    pilot.start()
