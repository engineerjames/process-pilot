import importlib  # noqa: D100
import logging
import os
import pkgutil
import subprocess
import threading
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin
from process_pilot.plugins.file_ready import FileReadyPlugin
from process_pilot.plugins.pipe_ready import PipeReadyPlugin
from process_pilot.plugins.tcp_ready import TCPReadyPlugin
from process_pilot.process import Process, ProcessManifest, ProcessStats
from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from collections.abc import Callable


class ProcessPilot:
    """Class that manages a manifest-driven set of processes."""

    def __init__(
        self,
        manifest: ProcessManifest,
        plugin_directory: Path | None = None,
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

        self.ready_strategies: dict[str, Callable[[Process, float], bool]] = {}
        self.stat_handlers: list[Callable[[list[ProcessStats]], None]] = []

        # Load default plugins regardless
        file_ready_plugin = FileReadyPlugin()
        pipe_ready_plugin = PipeReadyPlugin()
        tcp_ready_plugin = TCPReadyPlugin()

        self.plugin_registry: dict[str, Plugin] = {
            file_ready_plugin.name: file_ready_plugin,
            pipe_ready_plugin.name: pipe_ready_plugin,
            tcp_ready_plugin.name: tcp_ready_plugin,
        }

        # Load plugins from provided directory if necessary
        logging.debug("Loading plugins")
        if plugin_directory:
            self.load_plugins(plugin_directory)

        logging.debug("Loaded the following plugins: %s", self.plugin_registry.values())

        logging.debug("Registering plugins")
        self.register_plugins(list(self.plugin_registry.values()))

    def load_plugins(self, plugin_dir: Path) -> None:
        """
        Load plugins from the specified directory.

        :param plugin_dir: The directory to load plugins from
        """
        for _finder, name, _ispkg in pkgutil.iter_modules([str(plugin_dir)]):
            module = importlib.import_module(name)
            for attr in dir(module):
                cls = getattr(module, attr)
                if isinstance(cls, type) and issubclass(cls, Plugin) and cls is not Plugin:
                    plugin = cls()

                    if plugin.name in self.plugin_registry:
                        logging.warning(
                            "Plugin %s already registered--overwriting",
                            plugin.name,
                        )

                    self.plugin_registry[plugin.name] = plugin

    def register_plugins(self, plugins: list[Plugin]) -> None:
        """Register plugins and their hooks/strategies."""
        for plugin in plugins:
            if plugin.name in self.plugin_registry:
                logging.warning(
                    "Plugin %s already registered--overwriting",
                    plugin.name,
                )
            self.plugin_registry[plugin.name] = plugin

            hooks = plugin.register_hooks()
            strategies = plugin.register_strategies()
            stat_handlers = plugin.register_stats_handlers()

            # Register hooks for processes that specify this plugin
            for process in self._manifest.processes:
                if plugin.name in process.plugins:
                    for hook_type, hook_list in hooks.items():
                        if hook_type not in process.hooks:
                            process.hooks[hook_type] = []
                        process.hooks[hook_type].extend(hook_list)

            # Register strategies globally
            self.ready_strategies.update(strategies)

            # Register stat handlers globally
            self.stat_handlers.extend(stat_handlers)

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

            ProcessPilot._execute_hooks(
                process=entry,
                popen=None,
                hook_type="pre_start",
            )

            new_popen_result = subprocess.Popen(  # noqa: S603
                entry.command,
                encoding="utf-8",
                env=process_env,
            )

            if entry.ready_strategy:
                if entry.wait_until_ready(self.ready_strategies):
                    logging.debug("Process %s signaled ready", entry.name)
                else:
                    error_message = f"Process {entry.name} failed to signal ready"
                    raise RuntimeError(error_message)  # TODO: Should we handle this differently?
            else:
                logging.debug("No ready strategy for process %s", entry.name)

            ProcessPilot._execute_hooks(
                process=entry,
                popen=new_popen_result,
                hook_type="post_start",
            )

            self._running_processes.append((entry, new_popen_result))

    @staticmethod
    def _execute_hooks(process: Process, popen: subprocess.Popen[str] | None, hook_type: ProcessHookType) -> None:
        if hook_type not in process.hooks or len(process.hooks[hook_type]) == 0:
            logging.warning("No %s hooks available for process: '%s'", hook_type, process.name)
            return

        logging.debug("Executing hooks for process: '%s'", process.name)
        for hook in process.hooks[hook_type]:
            hook(process, popen)

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

            ProcessPilot._execute_hooks(
                process=process_entry,
                popen=process,
                hook_type="on_shutdown",
            )

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

                    restarted_process = subprocess.Popen(  # noqa: S603
                        process_entry.command,
                        encoding="utf-8",
                        env={**os.environ, **process_entry.env},
                    )

                    processes_to_add.append(
                        (
                            process_entry,
                            restarted_process,
                        ),
                    )

                    ProcessPilot._execute_hooks(
                        process=process_entry,
                        popen=restarted_process,
                        hook_type="on_restart",
                    )
                case _:
                    logging.error(
                        "Shutdown strategy not handled: %s",
                        process_entry.shutdown_strategy,
                    )

        self._remove_processes(processes_to_remove)

        # Collect and process stats
        # TODO: This should likely be moved to a separate method, but also
        #      should be done in a separate thread to avoid blocking the main loop
        process_stats = [process_entry.get_stats() for process_entry, _ in self._running_processes]

        # Call registered stats handlers
        for handler in self.stat_handlers:
            try:
                handler(process_stats)
            except Exception:
                logging.exception("Error in stats handler %s", handler)

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
