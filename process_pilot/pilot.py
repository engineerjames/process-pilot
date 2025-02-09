import contextlib  # noqa: D100
import importlib
import logging
import logging.config
import os
import pkgutil
import platform
import signal
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path
from threading import Lock
from time import sleep
from typing import Any, cast, overload

import psutil

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
from process_pilot.process import Process, ProcessManifest, ProcessState, ProcessStats, ProcessStatus
from process_pilot.types import ProcessHookType


class ProcessPilot:
    """Class that manages a manifest-driven set of processes."""

    def __init__(
        self,
        manifest: ProcessManifest,
        plugin_directory: Path | None = None,
        process_poll_interval: float = 0.1,
        ready_check_interval: float = 0.1,
        logger_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Construct the ProcessPilot class.

        :param manifest: Manifest that contains a definition for each process
        :param poll_interval: The amount of time to wait in-between service checks in seconds
        :param ready_check_interval: The amount of time to wait in-between readiness checks in seconds
        :param logger_config: Optional logger configuration dictionary
        """
        self._manifest = manifest
        self._control_server: ControlServer | None = None
        self._control_server_thread: threading.Thread | None = None
        self._process_poll_interval_secs = process_poll_interval
        self._ready_check_interval_secs = ready_check_interval
        self._running_processes_lock = Lock()
        self._running_processes: list[tuple[Process, subprocess.Popen[str]]] = []
        self._shutting_down: bool = False
        self._creation_flags: int = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            if platform.system() == "Windows"
            else 0  # The default
        )

        self._thread = threading.Thread(target=self._run)

        # Configure the logger
        if logger_config:
            logging.config.dictConfig(logger_config)
        else:
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

    def _terminate_similar_process_names(self, full_path: str | None) -> None:
        # Also, check if there are any other processes with the same process name in
        # case we are dealing with a Pyinstaller-created executable that uses a bootloader
        # process to launch the main executable
        if not full_path:
            logging.debug("No full path provided to terminate similar process names")
            return

        with contextlib.suppress(psutil.NoSuchProcess):
            for p in psutil.process_iter(["name"]):
                if p.info["name"] == Path(full_path).name:
                    logging.info("Terminating process with same name: %s", p.pid)
                    p.terminate()

    def _terminate_process_tree(self, process: subprocess.Popen[str], timeout: float | None = None) -> None:
        """
        Terminate a process and all its children recursively in a cross-platform way.

        :param process: The subprocess.Popen instance to terminate
        :param timeout: Timeout in seconds to wait for process termination
        """
        if not process.pid:
            logging.info("Process %s already terminated -- not scanning process tree", process)
            return

        try:
            parent = psutil.Process(process.pid)

            if platform.system() == "Windows":
                # On Windows, we need to handle the process tree explicitly
                children = parent.children(recursive=True)

                logging.info("Found %i children for process %s", len(children), process.pid)

                # First terminate children
                for child in children:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.terminate()

                # Then terminate parent and all processes in the same process group
                parent.terminate()

                self._terminate_similar_process_names(parent.name())

                _, alive = psutil.wait_procs([parent, *children], timeout=timeout)

                # If any processes are still alive, kill them
                for p in alive:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        p.kill()
            else:
                # On Unix-like systems (Linux/macOS), we can use process groups instead
                try:
                    # Send SIGTERM to the process group
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logging.info("Process %s did not terminate gracefully - killing", process.pid)
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    logging.warning("Process %s not found", process.pid)

        except (psutil.NoSuchProcess, ProcessLookupError):
            # Process may have already terminated, but we want to ensure we clean up
            # any orphaned processes
            if not isinstance(process.args, list):
                logging.warning("Arguments to process not a list as expected.")
                return

            if len(process.args) == 0:
                logging.warning("No arguments provided to process.")
                return

            self._terminate_similar_process_names(process.args[0])
        except Exception as e:  # noqa: BLE001
            logging.warning("Unexpected error while terminating process tree: %s", str(e))

    def restart_processes(self, process_names: list[str] | str) -> None:  # noqa: C901
        """
        Restart specific processes by name.

        :param process_names: List of process name(s) to restart, or a single process name

        :raises ValueError: If any process name is not found
        """
        processes_to_restart: dict[str, tuple[Process, subprocess.Popen[str]]] = {}

        if isinstance(process_names, str):
            process_names = [process_names]

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

            process_entry.update_status(
                status=ProcessState.STOPPING,
                pid=process.pid,
                return_code=None,
            )

            self._terminate_process_tree(process, timeout=process_entry.timeout)

            process_entry.update_status(
                status=ProcessState.STOPPED,
                return_code=process.returncode,
            )

            # Ensure dependencies are satisfied
            for dep in process_entry.dependencies:
                dep = cast(Process, dep)
                dep_proc = self.get_process_by_name(dep.name)

                if not dep_proc:
                    logging.warning("Dependency %s not found for process %s", dep.name, name)
                    continue

                if dep_proc.get_status().status != ProcessState.RUNNING:
                    logging.warning("Dependency %s not satisfied for process %s", dep.name, name)
                    self.start_process(dep.name)
                    continue

            # Start new process
            new_process = subprocess.Popen(  # noqa: S603
                process_entry.command,
                encoding="utf-8",
                env={**os.environ, **process_entry.env},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=process_entry.working_directory,
                creationflags=self._creation_flags,
            )

            # Update running processes list
            with self._running_processes_lock:
                self._running_processes.remove((process_entry, process))
                self._running_processes.append((process_entry, new_process))

            # Execute restart hooks
            self.execute_lifecycle_hooks(process=process_entry, popen=new_process, hook_type="on_restart")

            # Wait for readiness if strategy exists
            if process_entry.ready_strategy and not process_entry.wait_until_ready():
                error_message = f"Process {name} failed to signal ready after restart"
                new_process.terminate()
                raise RuntimeError(error_message)

            # Update process properties
            process_entry.update_status(
                status=ProcessState.RUNNING,
                pid=process.pid,
                return_code=None,
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
        except Exception as e:  # noqa: BLE001
            logging.exception("Unexpected error in main loop: %s", str(e))
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

    def get_manifest_processes(self) -> list[Process]:
        """Get all processes specified in the manifest."""
        return deepcopy(self._manifest.processes)

    @overload
    def get_running_process(self, process_id: None = None) -> list[ProcessStatus] | None: ...

    @overload
    def get_running_process(self, process_id: int) -> ProcessStatus | None: ...

    @overload
    def get_running_process(self, process_id: str) -> ProcessStatus | None: ...

    def get_running_process(
        self,
        process_id: int | str | None = None,
    ) -> list[ProcessStatus] | ProcessStatus | None:
        """
        Get a running process by its ID.

        :param process_id: The ID of the process to retrieve (integer PID or string name).
                           If None, return all processes.
        """
        if not process_id:
            return [deepcopy(proc.get_status()) for proc, _ in self._running_processes]

        for manifest_details, proc in self._running_processes:
            if (isinstance(process_id, str) and manifest_details.name == process_id) or (
                isinstance(process_id, int) and proc.pid == process_id
            ):
                return deepcopy(manifest_details.get_status())

        return None

    def get_process_by_name(self, name: str) -> Process | None:
        """Get a process' manifest details by its name."""
        for process_entry in self._manifest.processes:
            if process_entry.name == name:
                return process_entry
        return None

    def start_process(self, name: str) -> None:
        """Start a specific process by its manifest name."""
        process = self.get_process_by_name(name)
        if not process:
            msg = f"Process '{name}' not found"
            raise ValueError(msg)

        process.update_status(
            status=ProcessState.STARTING,
            return_code=None,
        )

        logging.info("Starting process: %s", name)
        new_popen_result = subprocess.Popen(  # noqa: S603
            process.command,
            encoding="utf-8",
            env={**os.environ, **process.env},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=process.working_directory,
            creationflags=self._creation_flags,
        )
        self.set_process_affinity(new_popen_result, process.affinity)

        process.update_status(
            status=ProcessState.RUNNING,
            pid=new_popen_result.pid,
            return_code=None,
        )

        with self._running_processes_lock:
            self._running_processes.append((process, new_popen_result))

    def stop_process(self, name: str) -> None:
        """
        Stop a specific process by its manifest name.

        :param name: Name of the process to stop
        :raises ValueError: If process name is not found
        """
        process_to_stop = next(
            ((entry, proc) for entry, proc in self._running_processes if entry.name == name),
            None,
        )

        if not process_to_stop:
            msg = f"Process '{name}' not found"
            raise ValueError(msg)

        process_entry, popen = process_to_stop

        logging.info("Stopping process: %s", name)
        process_entry.update_status(
            status=ProcessState.STOPPING,
            pid=popen.pid,
            return_code=None,
        )

        self._terminate_process_tree(popen, timeout=process_entry.timeout)

        process_entry.update_status(
            status=ProcessState.STOPPED,
            return_code=popen.returncode,
        )

        with self._running_processes_lock:
            self._running_processes.remove((process_entry, popen))

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

            entry.update_status(
                status=ProcessState.STARTING,
            )

            ProcessPilot.execute_lifecycle_hooks(
                process=entry,
                popen=None,
                hook_type="pre_start",
            )

            new_popen_result = subprocess.Popen(  # noqa: S603
                entry.command,
                encoding="utf-8",
                env=process_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=entry.working_directory,
                creationflags=self._creation_flags,
            )

            self.set_process_affinity(new_popen_result, entry.affinity)

            entry.update_status(
                status=ProcessState.RUNNING,
                pid=new_popen_result.pid,
            )

            if entry.ready_strategy:
                if entry.wait_until_ready():
                    logging.debug("Process %s signaled ready", entry.name)
                else:
                    error_message = f"Process {entry.name} failed to signal ready - terminating"
                    self._terminate_process_tree(new_popen_result, timeout=entry.timeout)
                    raise RuntimeError(error_message)  # TODO: Should we handle this differently?
            else:
                logging.debug("No ready strategy for process %s", entry.name)

            ProcessPilot.execute_lifecycle_hooks(
                process=entry,
                popen=new_popen_result,
                hook_type="post_start",
            )

            with self._running_processes_lock:
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

            # Ensure we kill off the entire process tree
            # TODO: If the process is already terminated, how do we handle this?
            # Killing off the process tree likely won't work because we can't find the
            # orphans anymore.  We might need a mechanism to track orphaned processes
            # ourselves.  Curse you Windows...
            self._terminate_process_tree(process)

            processes_to_remove.append(process_entry)

            process_entry.update_status(
                status=ProcessState.STOPPED,
                return_code=process.returncode,
            )

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

                    # Immediately return to avoid further processing
                    return
                case "do_not_restart":
                    logging.warning(
                        "%s shutdown with return code %i.",
                        process_entry,
                        process.returncode,
                    )
                case "restart":
                    logging.warning(
                        "%s shutdown with return code %i.  Restarting...",
                        process_entry.name,
                        process.returncode,
                    )

                    process_entry.update_status(
                        status=ProcessState.STARTING,
                        return_code=process.returncode,
                    )

                    logging.debug(
                        "Running command %s",
                        process_entry.command,
                    )

                    restarted_process = subprocess.Popen(  # noqa: S603
                        process_entry.command,
                        encoding="utf-8",
                        env={**os.environ, **process_entry.env},
                        stdout=subprocess.DEVNULL,  # TODO: Allow users to customize this
                        stderr=subprocess.DEVNULL,
                        cwd=process_entry.working_directory,
                        creationflags=self._creation_flags,
                    )

                    self.set_process_affinity(restarted_process, process_entry.affinity)

                    process_entry.update_status(
                        status=ProcessState.RUNNING,
                        pid=restarted_process.pid,
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

        with self._running_processes_lock:
            self._running_processes.extend(processes_to_add)

    def set_process_affinity(self, process: subprocess.Popen[str], affinity: list[int] | None) -> None:
        """
        Set the CPU affinity for a given process. Not supported in Mac OS X.

        :param process: Process to set the affinity for
        """
        # If we're on MAC OS X - Do nothing
        # OS X does not export interfaces that identify processors or control thread
        # placement—explicit thread to processor binding is not supported. Instead, the
        # kernel manages all thread placement. Applications expect that the scheduler will,
        # under most circumstances, run its threads using a good processor placement with
        # respect to cache affinity.
        if platform.system() == "Darwin" or affinity is None:
            # Intentionally do nothing
            return

        try:
            p = psutil.Process(process.pid)
            p.cpu_affinity(affinity)  # type: ignore[attr-defined, unused-ignore]
            logging.debug("Set process affinity for %s to %s", str(process.pid), str(affinity))
        except psutil.Error as e:
            logging.warning("Failed to set process affinity: %s", e)
        except psutil.AccessDenied:
            logging.warning("Insufficient permissions to set process affinity")
        except psutil.NoSuchProcess:
            logging.warning("Process %s not found", process.pid)
        except Exception as e:  # noqa: BLE001
            logging.warning("Unexpected error while setting process affinity: %s", str(e))

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
        with self._running_processes_lock:
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
        try:
            if self._thread.is_alive():
                logging.debug("Shutting down ProcessPilot...")
                self._shutting_down = True
                # TODO: Join thread here

            if self._control_server:
                logging.debug("Shutting down control server...")
                self._control_server.stop()
                if self._control_server_thread and self._control_server_thread.is_alive():
                    self._control_server_thread.join(5.0)  # TODO: Update this

                logging.debug("Control server stopped.")

            for process_entry, process in self._running_processes:
                process_entry.update_status(
                    status=ProcessState.STOPPING,
                    pid=process.pid,
                )

                logging.debug("Stopping process: %s", process_entry.name)

                self._terminate_process_tree(process, timeout=process_entry.timeout)

                try:
                    process.wait(process_entry.timeout)
                except subprocess.TimeoutExpired:
                    logging.warning(
                        "Detected timeout for %s: forceably killing.",
                        process_entry,
                    )
                    process.kill()
                    try:
                        process.wait(self._manifest.kill_timeout)
                    except subprocess.TimeoutExpired:
                        logging.critical("Process %s is unresponsive to kill! Forcing exit.", process_entry.name)
                        os._exit(1)  # Force exit the entire program

                process_entry.update_status(
                    status=ProcessState.STOPPED,
                    return_code=process.returncode,
                )

                logging.debug("Process %s stopped.", process_entry.name)
        finally:
            self._running_processes.clear()

    def is_running(self) -> bool:
        """Check if the ProcessPilot is currently running."""
        return self._thread.is_alive()


if __name__ == "__main__":
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "tests" / "examples" / "services.json")
    pilot = ProcessPilot(manifest)

    pilot.start()
