"""Main classes and definitions for ProcessPilot."""

import json
import logging
import subprocess
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from time import sleep

import yaml
from pydantic import BaseModel, Field


class ShutdownStrategy(str, Enum):
    """Enumeration that describes the strategy for if/when a service exits."""

    RESTART = "restart"  # Restart the service in question
    DO_NOT_RESTART = "do_not_restart"  # Leave it dead
    SHUTDOWN_EVERYTHING = "shutdown_everything"  # Take down everything else with it


class ProcessHookType(str, Enum):
    """Enumeration that describes when a given hook is to be executed."""

    PRE_START = "pre_start"
    POST_START = "post_start"
    ON_SHUTDOWN = "on_shutdown"
    ON_RESTART = "on_restart"


class InvalidHookTypeError(Exception):
    """Custom exception for invalid hook types."""

    def __init__(self, hook_type: ProcessHookType) -> None:
        """Construct custom exception for invalid hook types."""
        super().__init__(f"Hook type provided is invalid: {hook_type}")


class Process(BaseModel):
    """Pydantic model of an individual process that is being managed."""

    name: str
    path: Path
    args: list[str] = Field(default=[])
    timeout: float | None = None
    shutdown_strategy: ShutdownStrategy | None = ShutdownStrategy.RESTART
    dependencies: list["Process"] = Field(default=[])
    hooks: dict[ProcessHookType, list[Callable[["Process"], None]]] = Field(default={})

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
        if hook_type not in self.hooks:
            self.hooks[hook_type] = []

        if isinstance(callback, list):
            self.hooks[hook_type].extend(callback)
        else:
            self.hooks[hook_type].append(callback)


class ProcessManifest(BaseModel):
    """Pydantic model of each process that is being managed."""

    processes: list[Process]

    @classmethod
    def from_json(cls, path: Path) -> "ProcessManifest":
        """
        Load a JSON formatted process manifest.

        :param path: Path to the JSON file
        """
        with Path.open(path, "r") as f:
            json_data = json.loads(f.read())

        return cls(**json_data)

    @classmethod
    def from_yaml(cls, path: Path) -> "ProcessManifest":
        """
        Load a YAMLM formatted process manifest.

        :param path: Path to the YAML file
        """
        with Path.open(path, "r") as f:
            yaml_data = yaml.safe_load(f)

        return cls(**yaml_data)


class ProcessPilot:
    """Class that manages a manifest-driven set of processes."""

    def __init__(self, manifest: ProcessManifest, poll_interval: float = 0.1) -> None:
        """
        Construct the ProcessPilot class.

        :param manifest: Manifest that contains a definition for each process
        :param poll_interval: The amount of time to wait in-between service checks
        """
        self._manifest = manifest
        self._poll_interval = poll_interval
        self._processes: list[tuple[Process, subprocess.Popen[str]]] = []
        self._shutting_down: bool = False

        # Configure the logger
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

    def start(self) -> None:
        """Start all services."""
        try:
            logging.debug("Starting process pilot - Initializing processes.")
            self._initialize_processes()

            logging.debug("Entering main execution loop")
            while not self._shutting_down:
                self._process_loop()

                sleep(self._poll_interval)

                if not self._processes:
                    logging.warning("No running processes to manage--shutting down.")
                    self.stop()

        except KeyboardInterrupt:
            logging.warning("Detected keyboard interrupt--shutting down.")
            self.stop()

    def _initialize_processes(self) -> None:
        """Initialize all processes prior to entering the monitoring loop."""
        for entry in self._manifest.processes:
            logging.debug(
                "Executing command: %s",
                entry.command,
            )

            ProcessPilot._execute_hooks(entry, ProcessHookType.PRE_START)
            new_popen_result = subprocess.Popen(entry.command, encoding="utf-8")  # noqa: S603
            ProcessPilot._execute_hooks(entry, ProcessHookType.POST_START)
            self._processes.append((entry, new_popen_result))

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

        for process_entry, process in self._processes:
            result = process.poll()

            # Process has not exited yet
            if result is None:
                continue

            processes_to_remove.append(process_entry)

            ProcessPilot._execute_hooks(process_entry, ProcessHookType.ON_SHUTDOWN)

            match process_entry.shutdown_strategy:
                case ShutdownStrategy.SHUTDOWN_EVERYTHING:
                    logging.warning(
                        "%s shutdown with return code %i - shutting down everything.",
                        process_entry,
                        process.returncode,
                    )
                    self.stop()
                case ShutdownStrategy.DO_NOT_RESTART:
                    logging.warning(
                        "%s shutdown with return code %i.",
                        process_entry,
                        process.returncode,
                    )
                case ShutdownStrategy.RESTART:
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
                            subprocess.Popen(process_entry.command, encoding="utf-8"),  # noqa: S603
                        ),
                    )

                    ProcessPilot._execute_hooks(process_entry, ProcessHookType.ON_RESTART)
                case _:
                    logging.error(
                        "Shutdown strategy not handled: %s",
                        process_entry.shutdown_strategy,
                    )

        self._remove_processes(processes_to_remove)
        self._processes.extend(processes_to_add)

    def _remove_processes(self, processes_to_remove: list[Process]) -> None:
        for p in processes_to_remove:
            processes_to_investigate = [(proc, popen) for (proc, popen) in self._processes if proc == p]

            for proc_to_inv in processes_to_investigate:
                _, popen_obj = proc_to_inv
                if popen_obj.returncode is not None:
                    logging.debug(
                        "Removing process with output: %s",
                        popen_obj.communicate(),
                    )
                    self._processes.remove(proc_to_inv)

    def stop(self) -> None:
        """Stop all services."""
        self._shutting_down = True

        for process_entry, process in self._processes:
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
