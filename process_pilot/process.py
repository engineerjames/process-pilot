import json  # noqa: D100
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import psutil
import yaml
from pydantic import BaseModel, Field, model_validator

from process_pilot.types import ProcessHookType, ShutdownStrategy


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

    ready_strategy: str | None = None
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

    def wait_until_ready(
        self,
        ready_strategies: dict[str, Callable[["Process", float], bool]],
    ) -> bool:
        """Wait for process to signal readiness."""
        if self.ready_strategy not in ready_strategies:
            error_message = f"Ready strategy not found: {self.ready_strategy}"
            raise ValueError(error_message)

        return ready_strategies[self.ready_strategy](self, 0.1)


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
