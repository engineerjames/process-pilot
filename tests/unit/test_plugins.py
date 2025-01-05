import os  # noqa: INP001
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import Popen
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from process_pilot.pilot import ProcessPilot
from process_pilot.plugin import Plugin
from process_pilot.plugins.file_ready import FileReadyPlugin
from process_pilot.plugins.pipe_ready import PipeReadyPlugin
from process_pilot.plugins.tcp_ready import TCPReadyPlugin
from process_pilot.process import Process, ProcessManifest, ProcessStats
from process_pilot.types import ProcessHookType


# FileReadyPlugin Tests
def test_file_ready_plugin_success(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="file",
        ready_params={"path": "/tmp/ready.txt"},
        ready_timeout_sec=5.0,
    )

    mocker.patch("pathlib.Path.exists", return_value=True)

    plugin = FileReadyPlugin()
    assert plugin._wait_file_ready(process, 0.1)


def test_file_ready_plugin_timeout(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="file",
        ready_params={"path": "/tmp/ready.txt"},
        ready_timeout_sec=1.0,
    )

    mocker.patch("pathlib.Path.exists", return_value=False)

    plugin = FileReadyPlugin()
    assert not plugin._wait_file_ready(process, 0.1)


def test_file_ready_plugin_missing_path() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="file",
        ready_params={},
        ready_timeout_sec=5.0,
    )

    plugin = FileReadyPlugin()
    with pytest.raises(RuntimeError, match="Path not specified for file ready strategy"):
        plugin._wait_file_ready(process, 0.1)


# PipeReadyPlugin Tests
def test_pipe_ready_plugin_unix_success(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={"path": "/tmp/pipe_ready"},
        ready_timeout_sec=5.0,
    )

    mocker.patch("pathlib.Path.exists", return_value=True)
    mock_open = mocker.patch("os.fdopen", mock.mock_open(read_data="ready"))
    mock_os_open = mocker.patch("os.open", return_value=3)
    _ = mocker.patch("os.mkfifo")
    mock_unlink = mocker.patch("pathlib.Path.unlink")

    plugin = PipeReadyPlugin()
    assert plugin._wait_pipe_ready_unix(process, 0.1)
    mock_os_open.assert_called_once_with(Path("/tmp/pipe_ready"), os.O_RDONLY | os.O_NONBLOCK)
    mock_open.assert_called_once_with(3)
    mock_unlink.assert_called()


def test_pipe_ready_plugin_unix_timeout(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={"path": "/tmp/pipe_ready"},
        ready_timeout_sec=1.0,
    )

    if Path("/tmp/pipe_ready").exists():
        Path("/tmp/pipe_ready").unlink()

    mocker.patch("pathlib.Path.exists", return_value=False)

    plugin = PipeReadyPlugin()
    assert not plugin._wait_pipe_ready_unix(process, 0.1)


def test_pipe_ready_plugin_unix_missing_path() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={},
        ready_timeout_sec=5.0,
    )

    plugin = PipeReadyPlugin()
    with pytest.raises(RuntimeError, match="Path not specified for pipe ready strategy"):
        plugin._wait_pipe_ready_unix(process, 0.1)


def test_pipe_ready_plugin_windows_success(mocker: MockerFixture) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-specific test")

    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={"path": "\\\\.\\pipe\\test_process_ready"},
        ready_timeout_sec=5.0,
    )

    mock_win32pipe = mocker.patch("win32pipe.CreateNamedPipe")
    mock_win32file = mocker.patch("win32file.ReadFile", return_value=(0, b"ready"))

    plugin = PipeReadyPlugin()
    assert plugin._wait_pipe_ready_windows(process, 0.1)
    mock_win32pipe.assert_called_once()
    mock_win32file.assert_called_once()


def test_pipe_ready_plugin_windows_timeout(mocker: MockerFixture) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-specific test")

    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={"path": "\\\\.\\pipe\\test_process_ready"},
        ready_timeout_sec=1.0,
    )

    mock_win32pipe = mocker.patch("win32pipe.CreateNamedPipe")
    mock_win32file = mocker.patch("win32file.ReadFile", side_effect=Exception)

    plugin = PipeReadyPlugin()
    assert not plugin._wait_pipe_ready_windows(process, 0.1)
    mock_win32pipe.assert_called_once()
    mock_win32file.assert_called()


def test_pipe_ready_plugin_windows_missing_path() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-specific test")

    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={},
        ready_timeout_sec=5.0,
    )

    plugin = PipeReadyPlugin()
    with pytest.raises(RuntimeError, match="Path not specified for pipe ready strategy"):
        plugin._wait_pipe_ready_windows(process, 0.1)


# TCPReadyPlugin Tests
def test_tcp_ready_plugin_success(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="tcp",
        ready_params={"port": 8080},
        ready_timeout_sec=5.0,
    )

    mock_socket = mocker.patch("socket.create_connection")

    plugin = TCPReadyPlugin()
    assert plugin._wait_tcp_ready(process, 0.1)
    mock_socket.assert_called_once_with(("localhost", 8080), timeout=1.0)


def test_tcp_ready_plugin_timeout(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="tcp",
        ready_params={"port": 8080},
        ready_timeout_sec=1.0,
    )

    mock_socket = mocker.patch("socket.create_connection", side_effect=socket.error)

    plugin = TCPReadyPlugin()
    assert not plugin._wait_tcp_ready(process, 0.1)
    mock_socket.assert_called()


def test_tcp_ready_plugin_missing_port() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="tcp",
        ready_params={},
        ready_timeout_sec=5.0,
    )

    plugin = TCPReadyPlugin()
    with pytest.raises(RuntimeError, match="Port not specified for TCP ready strategy"):
        plugin._wait_tcp_ready(process, 0.1)


def test_process_stats_creation() -> None:
    process = Process(name="test_process", path=Path("/test/path"))
    stats = process.get_stats()

    assert isinstance(stats, ProcessStats)
    assert stats.name == "test_process"
    assert stats.path == Path("/test/path")
    assert stats.memory_usage_mb == 0.0
    assert stats.cpu_usage_percent == 0.0


class MockStatsPlugin(Plugin):
    """Test plugin implementation for verifying process statistics handling."""

    def __init__(self) -> None:
        """Initialize the mock stats plugin with default values."""
        self.stats_called = False
        self.last_stats: list[ProcessStats] = []

    @property
    def name(self) -> str:
        """Return the name of the plugin."""
        return "mock_stats_plugin"

    def get_lifecycle_hooks(self) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
        """
        Return a dictionary of process hooks for the plugin.

        :returns: Empty dictionary as this is a mock plugin.
        """
        return {}

    def get_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
        """
        Register any ready strategies implemented by this plugin.

        :returns: Empty dictionary as this is a mock plugin.
        """
        return {}

    def get_stats_handlers(self) -> list[Callable[[list["ProcessStats"]], None]]:
        """
        Register handlers for process statistics.

        :returns: List containing the stats handler function.
        """
        return [self._handle_stats]

    def _handle_stats(self, stats: list[ProcessStats]) -> None:
        self.stats_called = True
        self.last_stats = stats


def test_stats_handler_registration() -> None:
    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest)
    plugin = MockStatsPlugin()

    pilot.register_plugins([plugin])
    assert len(pilot.stat_handlers) == 1


def test_stats_handler_execution(mocker: MockerFixture) -> None:
    manifest = ProcessManifest(processes=[Process(name="test_process", path=Path("/test/path"))])

    pilot = ProcessPilot(manifest)
    plugin = MockStatsPlugin()
    pilot.register_plugins([plugin])

    mock_popen = mocker.Mock()
    mock_popen.poll.return_value = None
    mock_popen.pid = 1234  # Set a valid integer PID
    pilot._running_processes = [(manifest.processes[0], mock_popen)]
    pilot._running_processes = [(manifest.processes[0], mock_popen)]

    pilot._process_loop()

    assert plugin.stats_called
    assert len(plugin.last_stats) == 1
    assert plugin.last_stats[0].name == "test_process"


def test_stats_handler_exception(mocker: MockerFixture) -> None:
    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest)

    def failing_handler(_: list[ProcessStats]) -> None:
        msg = "Handler failed"
        raise RuntimeError(msg)

    pilot.stat_handlers.append(failing_handler)
    mock_logger = mocker.patch("logging.exception")

    pilot._process_loop()

    mock_logger.assert_called_once()


def test_multiple_stats_handlers(mocker: MockerFixture) -> None:
    manifest = ProcessManifest(processes=[Process(name="test_process", path=Path("/test/path"))])

    pilot = ProcessPilot(manifest)
    plugin1 = MockStatsPlugin()
    plugin2 = MockStatsPlugin()
    pilot.register_plugins([plugin1, plugin2])

    mock_popen = mocker.Mock()
    mock_popen.poll.return_value = None
    mock_popen.pid = 1234  # Set a valid integer PID
    pilot._running_processes = [(manifest.processes[0], mock_popen)]

    pilot._process_loop()

    assert plugin1.stats_called
    assert plugin2.stats_called
    assert len(plugin1.last_stats) == 1
    assert len(plugin2.last_stats) == 1


def test_stats_handler_multiple_processes(mocker: MockerFixture) -> None:
    """Test that stats handlers receive data from multiple processes."""
    manifest = ProcessManifest(
        processes=[
            Process(name="test_process1", path=Path("/test/path1")),
            Process(name="test_process2", path=Path("/test/path2")),
        ],
    )

    pilot = ProcessPilot(manifest)
    plugin = MockStatsPlugin()
    pilot.register_plugins([plugin])

    mock_popen1 = mocker.Mock()
    mock_popen1.poll.return_value = None
    mock_popen1.pid = 1234

    mock_popen2 = mocker.Mock()
    mock_popen2.poll.return_value = None
    mock_popen2.pid = 5678

    pilot._running_processes = [(manifest.processes[0], mock_popen1), (manifest.processes[1], mock_popen2)]

    pilot._process_loop()

    assert plugin.stats_called
    assert len(plugin.last_stats) == 2
    assert {stat.name for stat in plugin.last_stats} == {"test_process1", "test_process2"}


def test_stats_handler_with_dead_process(mocker: MockerFixture) -> None:
    """Test that stats handlers handle processes that have died."""
    manifest = ProcessManifest(
        processes=[Process(name="test_process", path=Path("/test/path"), shutdown_strategy="do_not_restart")],
    )

    pilot = ProcessPilot(manifest)
    plugin = MockStatsPlugin()
    pilot.register_plugins([plugin])

    mock_popen = mocker.Mock()
    mock_popen.poll.return_value = 1  # Process has exited
    mock_popen.pid = 1234
    mock_popen.returncode = 1
    pilot._running_processes = [(manifest.processes[0], mock_popen)]

    pilot._process_loop()

    assert plugin.stats_called
    assert len(plugin.last_stats) == 0  # No stats for dead process


def test_plugin_registering_all_hook_types() -> None:
    """Test registering hooks for all available hook types."""

    class AllHooksPlugin(Plugin):
        @property
        def name(self) -> str:
            return "all_hooks_plugin"

        def get_lifecycle_hooks(
            self,
        ) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
            def dummy_hook(_p: Process, _proc: Popen[str] | None) -> None:
                pass

            return {
                "pre_start": [dummy_hook],
                "post_start": [dummy_hook],
                "on_shutdown": [dummy_hook],
                "on_restart": [dummy_hook],
            }

        def get_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
            return {}

        def get_stats_handlers(self) -> list[Callable[[list[ProcessStats]], None]]:
            return []

    manifest = ProcessManifest(
        processes=[Process(name="test_process", path=Path("/test/path"), plugins=["all_hooks_plugin"])],
    )

    pilot = ProcessPilot(manifest)
    plugin = AllHooksPlugin()
    pilot.register_plugins([plugin])

    assert all(
        hook_type in pilot._manifest.processes[0].hook
        for hook_type in ["pre_start", "post_start", "on_shutdown", "on_restart"]
    )
    assert all(
        len(pilot._manifest.processes[0].hook[hook_type]) == 1 for hook_type in pilot._manifest.processes[0].hook
    )


def test_plugin_stats_handler_with_memory_spikes(mocker: MockerFixture) -> None:
    """Test that stats handlers correctly track memory spikes."""
    manifest = ProcessManifest(processes=[Process(name="test_process", path=Path("/test/path"))])

    pilot = ProcessPilot(manifest)
    plugin = MockStatsPlugin()
    pilot.register_plugins([plugin])

    mock_popen = mocker.Mock()
    mock_popen.poll.return_value = None
    mock_popen.pid = 1234

    # Mock psutil to simulate memory spikes
    mock_psutil = mocker.patch("psutil.Process")
    mock_psutil_instance = mock_psutil.return_value
    mock_psutil_instance.memory_info.return_value = mock.Mock(rss=1048576 * 100)  # 100 MB
    mock_psutil_instance.cpu_percent.return_value = 50.0

    pilot._running_processes = [(manifest.processes[0], mock_popen)]
    pilot._process_loop()

    assert plugin.stats_called
    assert len(plugin.last_stats) == 1
    assert plugin.last_stats[0].memory_usage_mb == 100.0
    assert plugin.last_stats[0].cpu_usage_percent == 50.0


def test_plugin_registration_order() -> None:  # noqa: C901
    """Test that plugin hooks and handlers are registered in the correct order."""
    execution_order: list[str] = []

    class OrderedPlugin1(Plugin):
        @property
        def name(self) -> str:
            return "plugin1"

        def get_lifecycle_hooks(
            self,
        ) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
            def hook(_p: Process, _proc: Popen[str] | None) -> None:
                execution_order.append("plugin1_hook")

            return {"pre_start": [hook]}

        def get_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
            return {}

        def get_stats_handlers(self) -> list[Callable[[list[ProcessStats]], None]]:
            def handler(_: list[ProcessStats]) -> None:
                execution_order.append("plugin1_stats")

            return [handler]

    class OrderedPlugin2(Plugin):
        @property
        def name(self) -> str:
            return "plugin2"

        def get_lifecycle_hooks(
            self,
        ) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
            def hook(_p: Process, _proc: Popen[str] | None) -> None:
                execution_order.append("plugin2_hook")

            return {"pre_start": [hook]}

        def get_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
            return {}

        def get_stats_handlers(self) -> list[Callable[[list[ProcessStats]], None]]:
            def handler(_: list[ProcessStats]) -> None:
                execution_order.append("plugin2_stats")

            return [handler]

    manifest = ProcessManifest(
        processes=[Process(name="test_process", path=Path("/test/path"), plugins=["plugin1", "plugin2"])],
    )

    pilot = ProcessPilot(manifest)
    pilot.register_plugins([OrderedPlugin1(), OrderedPlugin2()])

    # Execute hooks
    ProcessPilot._execute_hooks(
        process=manifest.processes[0],
        popen=None,
        hook_type="pre_start",
    )

    # Execute stats handlers
    for handler in pilot.stat_handlers:
        handler([])

    assert execution_order == [
        "plugin1_hook",
        "plugin2_hook",
        "plugin1_stats",
        "plugin2_stats",
    ]


def test_plugin_name_uniqueness() -> None:
    """Test that plugins have unique names."""

    class CustomPlugin(Plugin):
        @property
        def name(self) -> str:
            return "pipe_ready"  # Duplicate name

        def get_lifecycle_hooks(
            self,
        ) -> dict[ProcessHookType, list[Callable[["Process", Popen[str] | None], None]]]:
            return {}

        def get_ready_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
            return {}

        def get_stats_handlers(self) -> list[Callable[[list[ProcessStats]], None]]:
            return []

    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest)

    # Register built-in plugin first
    pilot.register_plugins([PipeReadyPlugin()])

    # Try to register plugin with duplicate name
    pilot.register_plugins([CustomPlugin()])

    # The last plugin in the list should be registered, with a warning logged
    assert len(pilot.plugin_registry) == 3  # 2 built-in plugins + 1 custom plugin that overrode the duplicate name
    assert isinstance(pilot.plugin_registry["pipe_ready"], CustomPlugin)
