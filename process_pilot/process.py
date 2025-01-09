import json  # noqa: D100
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psutil
import yaml
from pydantic import BaseModel, Field, model_validator

from process_pilot.plugin import LifecycleHookType, ReadyStrategyType, StatHandlerType
from process_pilot.types import ProcessHookType, ShutdownStrategy


@dataclass
class ProcessStats:
    """Container for process statistics."""

    name: str
    """Name of the process."""

    path: Path
    """Path to the process executable."""

    memory_usage_mb: float
    """Current memory usage in megabytes."""

    cpu_usage_percent: float
    """Current CPU usage as a percentage."""

    max_memory_usage_mb: float
    """Maximum memory usage recorded in megabytes."""

    max_cpu_usage_percent: float
    """Maximum CPU usage recorded as a percentage."""


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

    timeout: float | None = 5.0
    """The amount of time to wait for the process to exit before forcibly killing it."""

    shutdown_strategy: ShutdownStrategy | None = "restart"
    """The strategy to use when the process exits.  If not specified, the default is to restart the process."""

    dependencies: list[str] | list["Process"] = Field(default=[])
    """
    A list of dependencies that must be started before this process can be started.
    This is a list of other names in the manifest.
    """

    lifecycle_hooks: list[str] = Field(default=[])
    """
    An optional series of function names to call at various points in the process lifecycle. The function names must
    match the names of the functions in the provided plugin. That is, if you have loaded a plugin that provides
    function 'on_start' that you want called, the manifest entry should include 'on_start' in its list.
    """

    stat_handlers: list[str] = Field(default=[])
    """
    An optional series of function names to call whenever the process statistics are gathered. The function names must
    match the names of the functions in the provided plugin. That is, if you have loaded a plugin that provides
    function 'email_stats' that you want called, the manifest entry should include 'email_stats' in its list.
    """

    ready_strategy: str | None = None
    """Optional strategy to determine if the process is ready"""

    _runtime_info: ProcessRuntimeInfo = ProcessRuntimeInfo()
    """Runtime information about the process"""

    ready_timeout_sec: float = 5.0
    """The amount of time to wait for the process to signal readiness before giving up"""

    ready_params: dict[str, Any] = Field(default_factory=dict)
    """Additional parameters for the ready strategy"""

    _ready_strategy_function: ReadyStrategyType | None = None
    """The function that implements the ready strategy - set to private so that it will not be serialized"""

    @property
    def ready_strategy_function(self) -> ReadyStrategyType | None:
        """Return the ready strategy function for the process."""
        return self._ready_strategy_function

    @ready_strategy_function.setter
    def ready_strategy_function(self, strategy: ReadyStrategyType) -> None:
        """Set the ready strategy function for the process."""
        self._ready_strategy_function = strategy

    _lifecycle_hook_functions: dict[ProcessHookType, list[LifecycleHookType]] = {
        "on_restart": [],
        "on_shutdown": [],
        "post_start": [],
        "pre_start": [],
    }

    @property
    def lifecycle_hook_functions(self) -> dict[ProcessHookType, list[LifecycleHookType]]:
        """Return the lifecycle hooks dictionary."""
        return self._lifecycle_hook_functions

    @lifecycle_hook_functions.setter
    def lifecycle_hook_functions(self, hooks: dict[ProcessHookType, list[LifecycleHookType]]) -> None:
        """Set the lifecycle hooks dictionary."""
        self._lifecycle_hook_functions = hooks

    _stats_handler_functions: list[StatHandlerType] = []

    @property
    def stats_handler_functions(self) -> list[StatHandlerType]:
        """Return the stats handler functions."""
        return self._stats_handler_functions

    @stats_handler_functions.setter
    def stats_handler_functions(self, handlers: list[StatHandlerType]) -> None:
        """Set the stats handler functions."""
        self._stats_handler_functions = handlers

    @property
    def command(self) -> list[str]:
        """
        Return the path to the executable along with all arguments.

        :returns: A combined list of strings that contains both the executable path and all arguments
        """
        return [str(self.path), *self.args]

    def record_process_stats(self, pid: int) -> None:
        """Get the memory and cpu usage of a process by its PID."""
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

    def wait_until_ready(self) -> bool:
        """Wait for process to signal readiness."""
        # TODO: Don't think we need to wait for processes that have no dependents
        if not self.ready_strategy_function:
            return True

        return self.ready_strategy_function(self, 0.1)

    def get_stats(self) -> ProcessStats:
        """Create a ProcessStats object from current process state."""
        return ProcessStats(
            name=self.name,
            path=self.path,
            memory_usage_mb=self._runtime_info.memory_usage_mb,
            cpu_usage_percent=self._runtime_info.cpu_usage_percent,
            max_memory_usage_mb=self._runtime_info.max_memory_usage_mb,
            max_cpu_usage_percent=self._runtime_info.max_cpu_usage,
        )


class ProcessManifest(BaseModel):
    """Pydantic model of each process that is being managed."""

    processes: list[Process]
    """List of processes to be managed."""

    control_server: str | None = None
    """Name of the control server implementation to use - must be provided by a plugin."""

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

            if p.ready_strategy in ("file", "pipe"):
                # We need to normalize paths to their target OS
                p.ready_params["path"] = str(Path(p.ready_params["path"]))

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
