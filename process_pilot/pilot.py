import importlib  # noqa: D100
import logging
import os
import pkgutil
import subprocess
import sys
import threading
from pathlib import Path
from time import sleep

from process_pilot.plugin import (
    ControlServer,
    ControlServerType,
    LifecycleHookType,
    Plugin,
    ReadyStrategyType,
    StatHandlerType,
)
from process_pilot.plugins.file_ready import FileReadyPlugin
from process_pilot.plugins.pipe_ready import PipeReadyPlugin
from process_pilot.plugins.tcp_ready import TCPReadyPlugin
from process_pilot.process import Process, ProcessManifest, ProcessStats
from process_pilot.types import ProcessHookType


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
        self._control_server: ControlServer | None = None
        self._control_server_thread: threading.Thread | None = None
        self._process_poll_interval_secs = process_poll_interval
        self._ready_check_interval_secs = ready_check_interval
        self._running_processes: list[tuple[Process, subprocess.Popen[str]]] = []
        self._shutting_down: bool = False

        self._thread = threading.Thread(target=self._run)
        # self._control_thread = threading.Thread(target=self.)

        # Configure the logger
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

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

        logging.debug("Loaded the following plugins: %s", self.plugin_registry.keys())

        logging.debug("Registering plugins")
        self.register_plugins(list(self.plugin_registry.values()))

    def load_plugins(self, plugin_dir: Path) -> None:
        """
        Load plugins from the specified directory.

        :param plugin_dir: The directory to load plugins from
        """
        plugins_to_register: list[Plugin] = []

        try:
            sys.path.insert(0, str(plugin_dir))  # Add plugin directory to sys.path
            for _finder, name, _ispkg in pkgutil.iter_modules([str(plugin_dir)]):
                module = importlib.import_module(name)
                for attr in dir(module):
                    cls = getattr(module, attr)
                    if isinstance(cls, type) and issubclass(cls, Plugin) and cls is not Plugin:
                        plugin = cls()
                        plugins_to_register.append(plugin)
        except Exception:
            logging.exception("Unexpected error while loading plugin %s", name)
            raise
        finally:
            sys.path.pop(0)  # Remove plugin directory from sys.path
            for p in plugins_to_register:
                self.plugin_registry[p.name] = p

    def register_plugins(self, plugins: list[Plugin]) -> None:
        """Register plugins and their hooks/strategies."""
        hooks: dict[str, dict[ProcessHookType, list[LifecycleHookType]]] = {}
        strategies: dict[str, ReadyStrategyType] = {}
        stat_handlers: dict[str, list[StatHandlerType]] = {}
        control_servers: dict[str, ControlServerType] = {}

        for plugin in plugins:
            if plugin.name in self.plugin_registry:
                logging.warning(
                    "Plugin %s already registered--overwriting",
                    plugin.name,
                )
            self.plugin_registry[plugin.name] = plugin

            # Process each plugin
            new_hooks = plugin.get_lifecycle_hooks()
            new_strategies = plugin.get_ready_strategies()
            new_stat_handlers = plugin.get_stats_handlers()
            new_control_servers = plugin.get_control_servers()

            hooks.update(new_hooks)
            strategies.update(new_strategies)
            stat_handlers.update(new_stat_handlers)
            control_servers.update(new_control_servers)

        self._associate_plugins_with_processes(hooks, strategies, stat_handlers, control_servers)

    def _associate_plugins_with_processes(  # noqa: C901
        self,
        hooks: dict[str, dict[ProcessHookType, list[LifecycleHookType]]],
        strategies: dict[str, ReadyStrategyType],
        stat_handlers: dict[str, list[StatHandlerType]],
        control_servers: dict[str, ControlServerType],
    ) -> None:
        for process in self._manifest.processes:
            # Lifecycle hooks
            for hook_name in process.lifecycle_hooks:
                if hook_name not in hooks:
                    logging.warning(
                        "Hook %s not found in registry",
                        hook_name,
                    )
                    continue

                hooks_for_process = hooks[hook_name]

                for hook_type, hook_list in hooks_for_process.items():
                    process.lifecycle_hook_functions[hook_type].extend(hook_list)

            # Ready strategy
            if process.ready_strategy:
                if process.ready_strategy not in strategies:
                    logging.warning(
                        "Ready strategy %s not found in registry",
                        process.ready_strategy,
                    )
                else:
                    process.ready_strategy_function = strategies[process.ready_strategy]

            # Statistic Handlers
            for handler_name in process.stat_handlers:
                if handler_name not in stat_handlers:
                    logging.warning(
                        "Handler %s not found in registry",
                        handler_name,
                    )
                    continue

                handlers_for_process = stat_handlers[handler_name]
                process.stats_handler_functions.extend(handlers_for_process)

        if self._manifest.control_server:
            if self._manifest.control_server not in control_servers:
                logging.warning(
                    "Control server '%s' specified in the manifest wasn't found.",
                    self._manifest.control_server,
                )
            else:
                self._control_server = control_servers[self._manifest.control_server](self)

    def restart_processes(self, process_names: list[str] | str) -> None:
        """
        Restart specific processes by name.

        :param process_names: List of process name(s) to restart

        :raises ValueError: If any process name is not found
        """
        processes_to_restart: dict[str, tuple[Process, subprocess.Popen[str]]] = {}

        # Validate all process names first
        for name in process_names:
            found = False
            for process_entry, popen in self._running_processes:
                if process_entry.name == name:
                    processes_to_restart[name] = (process_entry, popen)
                    found = True
                    break
            if not found:
                msg = f"Process '{name}' not found"
                raise ValueError(msg)

        # Now restart the processes
        for name, (process_entry, process) in processes_to_restart.items():
            logging.info("Restarting process: %s", name)

            # Stop the current process
            process.terminate()
            try:
                process.wait(process_entry.timeout)
            except subprocess.TimeoutExpired:
                logging.warning("Process %s did not terminate gracefully - killing", name)
                process.kill()
                process.wait()

            # Start new process
            new_process = subprocess.Popen(  # noqa: S603
                process_entry.command,
                encoding="utf-8",
                env={**os.environ, **process_entry.env},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Update running processes list
            self._running_processes.remove((process_entry, process))
            self._running_processes.append((process_entry, new_process))

            # Execute restart hooks
            self.execute_lifecycle_hooks(process=process_entry, popen=new_process, hook_type="on_restart")

            # Wait for readiness if strategy exists
            if process_entry.ready_strategy and not process_entry.wait_until_ready():
                error_message = f"Process {name} failed to signal ready after restart"
                new_process.terminate()
                raise RuntimeError(error_message)

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

        if self._manifest.control_server and not self._control_server:
            error_message = f"Control server '{self._manifest.control_server}' not found"
            raise RuntimeError(error_message)

        if self._control_server:
            if self._control_server_thread:
                error_message = "Control server thread is already running"
                raise RuntimeError(error_message)
            self._control_server_thread = threading.Thread(target=self._control_server.start)

        if len(self._manifest.processes) == 0:
            error_message = "No processes to start"
            raise RuntimeError(error_message)

        self._shutting_down = False
        self._thread.start()
        if self._control_server_thread:
            self._control_server_thread.start()

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

            ProcessPilot.execute_lifecycle_hooks(
                process=entry,
                popen=None,
                hook_type="pre_start",
            )

            new_popen_result = subprocess.Popen(  # noqa: S603
                entry.command,
                encoding="utf-8",
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if entry.ready_strategy:
                if entry.wait_until_ready():
                    logging.debug("Process %s signaled ready", entry.name)
                else:
                    error_message = f"Process {entry.name} failed to signal ready - terminating"
                    new_popen_result.terminate()
                    raise RuntimeError(error_message)  # TODO: Should we handle this differently?
            else:
                logging.debug("No ready strategy for process %s", entry.name)

            ProcessPilot.execute_lifecycle_hooks(
                process=entry,
                popen=new_popen_result,
                hook_type="post_start",
            )

            self._running_processes.append((entry, new_popen_result))

    @staticmethod
    def execute_lifecycle_hooks(
        process: Process,
        popen: subprocess.Popen[str] | None,
        hook_type: ProcessHookType,
    ) -> None:
        """Execute the lifecycle hooks for a particular process."""
        if len(process.lifecycle_hook_functions[hook_type]) == 0:
            logging.warning("No %s hooks available for process: '%s'", hook_type, process.name)
            return

        logging.debug("Executing hooks for process: '%s'", process.name)
        for hook in process.lifecycle_hook_functions[hook_type]:
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

            ProcessPilot.execute_lifecycle_hooks(
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
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                    processes_to_add.append(
                        (
                            process_entry,
                            restarted_process,
                        ),
                    )

                    ProcessPilot.execute_lifecycle_hooks(
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

        self._collect_process_stats_and_notify()

        self._running_processes.extend(processes_to_add)

    def _collect_process_stats_and_notify(self) -> None:
        # Collect and process stats
        # TODO: This should likely be moved to a separate method, but also
        #      should be done in a separate thread to avoid blocking the main loop

        # Group stats by handler to avoid duplicate calls
        handler_to_stats: dict[StatHandlerType, list[ProcessStats]] = {}

        # Build mapping of handlers to their associated process stats
        for process_entry, _ in self._running_processes:
            for handler_func in process_entry.stats_handler_functions:
                if handler_func not in handler_to_stats:
                    handler_to_stats[handler_func] = []
                handler_to_stats[handler_func].append(process_entry.get_stats())

        # Call each handler exactly once with all its associated process stats
        for handler_func, stats in handler_to_stats.items():
            try:
                handler_func(stats)
            except Exception:
                logging.exception("Error in stats handler %s", handler_func)

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
        if self._thread.is_alive():
            self._shutting_down = True
            self._thread.join(5.0)  # TODO: Update this

        if self._control_server:
            self._control_server.stop()
            if self._control_server_thread and self._control_server_thread.is_alive():
                self._control_server_thread.join(5.0)  # TODO: Update this

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


if __name__ == "__main__":
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "tests" / "examples" / "services.json")
    pilot = ProcessPilot(manifest)

    pilot.start()
