import os  # noqa: INP001
import socket
import sys
from pathlib import Path
from subprocess import Popen
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from process_pilot.pilot import ProcessPilot
from process_pilot.plugin import ControlServerType, LifecycleHookType, Plugin, StatHandlerType
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
@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test")
def test_pipe_ready_plugin_windows_timeout(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        ready_strategy="pipe",
        ready_params={"path": "\\\\.\\pipe\\test_process_ready"},
        ready_timeout_sec=1.0,
    )

    _ = mocker.patch("win32file.ReadFile", side_effect=Exception)

    plugin = PipeReadyPlugin()
    assert not plugin._wait_pipe_ready_windows(process, 0.1)


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

    def get_stats_handlers(self) -> dict[str, list[StatHandlerType]]:
        """
        Register handlers for process statistics.

        :returns: List containing the stats handler function.
        """
        return {"mock_stat_handler": [self._handle_stats]}

    def _handle_stats(self, stats: list[ProcessStats]) -> None:
        self.stats_called = True
        self.last_stats = stats


def test_stats_handler_execution(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process",
                path=Path("/test/path"),
                stat_handlers=["mock_stat_handler"],
            ),
        ],
    )

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


def test_multiple_stats_handlers(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process",
                path=Path("/test/path"),
                stat_handlers=["mock_stat_handler"],
            ),
        ],
    )

    pilot = ProcessPilot(manifest)
    plugin1 = MockStatsPlugin()
    plugin2 = MockStatsPlugin()
    pilot.register_plugins([plugin1, plugin2])

    mock_popen = mocker.Mock()
    mock_popen.poll.return_value = None
    mock_popen.pid = 1234  # Set a valid integer PID
    pilot._running_processes = [(manifest.processes[0], mock_popen)]

    pilot._process_loop()

    assert plugin1.stats_called is False
    assert plugin2.stats_called
    assert len(plugin1.last_stats) == 0
    assert len(plugin2.last_stats) == 1


def test_stats_handler_multiple_processes(mocker: MockerFixture) -> None:
    """Test that stats handlers receive data from multiple processes."""
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process1",
                path=Path("/test/path1"),
                stat_handlers=["mock_stat_handler"],
            ),
            Process(
                name="test_process2",
                path=Path("/test/path2"),
                stat_handlers=["mock_stat_handler"],
            ),
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
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process",
                path=Path("/test/path"),
                shutdown_strategy="do_not_restart",
                stat_handlers=["mock_stat_handler"],
            ),
        ],
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

    assert plugin.stats_called is False
    assert len(plugin.last_stats) == 0  # No stats for dead process


def test_plugin_registering_all_hook_types(mocker: MockerFixture) -> None:
    """Test registering hooks for all available hook types."""

    class AllHooksPlugin(Plugin):
        def get_lifecycle_hooks(
            self,
        ) -> dict[str, dict[ProcessHookType, list[LifecycleHookType]]]:
            def dummy_hook(_p: Process, _proc: Popen[str] | None) -> None:
                pass

            return {
                "all_hooks": {
                    "pre_start": [dummy_hook],
                    "post_start": [dummy_hook],
                    "on_shutdown": [dummy_hook],
                    "on_restart": [dummy_hook],
                },
            }

    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process",
                path=Path("/test/path"),
                lifecycle_hooks=["all_hooks"],
            ),
        ],
    )

    pilot = ProcessPilot(manifest)
    plugin = AllHooksPlugin()
    pilot.register_plugins([plugin])

    assert all(
        hook_type in pilot._manifest.processes[0].lifecycle_hook_functions
        for hook_type in ["pre_start", "post_start", "on_shutdown", "on_restart"]
    )
    assert all(
        len(pilot._manifest.processes[0].lifecycle_hook_functions[hook_type]) == 1
        for hook_type in pilot._manifest.processes[0].lifecycle_hook_functions
    )


def test_plugin_stats_handler_with_memory_spikes(mocker: MockerFixture) -> None:
    """Test that stats handlers correctly track memory spikes."""
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test_process",
                path=Path("/test/path"),
                stat_handlers=["mock_stat_handler"],
            ),
        ],
    )

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


def test_plugin_name_uniqueness() -> None:
    """Test that plugins have unique names."""

    class CustomPlugin(Plugin):
        @property
        def name(self) -> str:
            return "PipeReadyPlugin"  # Duplicate name

    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest)

    # Register built-in plugin first
    pilot.register_plugins([PipeReadyPlugin()])

    # Try to register plugin with duplicate name
    pilot.register_plugins([CustomPlugin()])

    # The last plugin in the list should be registered, with a warning logged
    assert len(pilot.plugin_registry) == 3  # 2 built-in plugins + 1 custom plugin that overrode the duplicate name
    assert isinstance(pilot.plugin_registry["PipeReadyPlugin"], CustomPlugin)


def test_plugin_duplicate_registration(mocker: MockerFixture) -> None:
    """Test registering same plugin twice."""

    class DuplicatePlugin(Plugin):
        @property
        def name(self) -> str:
            return "duplicate"

    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest)
    plugin = DuplicatePlugin()

    pilot.register_plugins([plugin])

    mock_log = mocker.patch("process_pilot.pilot.logging.warning")
    pilot.register_plugins([plugin])
    mock_log.assert_called_once_with("Plugin %s already registered--overwriting", "duplicate")


def test_plugin_load_from_directory(tmp_path: Path) -> None:
    """Test loading plugins from a directory."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()

    plugin_file = plugin_dir / "test_plugin.py"
    plugin_file.write_text("""
from process_pilot.plugin import Plugin
class TestPlugin(Plugin):
  pass
    """)

    manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest, plugin_directory=plugin_dir)
    assert "TestPlugin" in pilot.plugin_registry


class TestControlServer:
    def __init__(self, pilot: ProcessPilot) -> None:
        self.pilot = pilot
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class ControlServerPlugin(Plugin):
    def get_control_servers(self) -> dict[str, ControlServerType]:
        return {"test": lambda pilot: TestControlServer(pilot)}


def test_control_server_plugin_registration() -> None:
    """Test registering a plugin with a control server implementation."""
    manifest = ProcessManifest(processes=[], control_server="test")

    pilot = ProcessPilot(manifest)
    plugin = ControlServerPlugin()
    pilot.register_plugins([plugin])

    assert pilot._control_server is not None
    assert isinstance(pilot._control_server, TestControlServer)

    pilot._control_server.start()
    assert pilot._control_server.started

    pilot._control_server.stop()
    assert pilot._control_server.stopped


def test_control_server_plugin_invalid_name() -> None:
    """Test registering a control server with an invalid name."""
    manifest = ProcessManifest(processes=[], control_server="invalid")

    pilot = ProcessPilot(manifest)
    plugin = ControlServerPlugin()
    pilot.register_plugins([plugin])
    with pytest.raises(RuntimeError, match="Control server 'invalid' not found"):
        pilot.start()


def test_multiple_control_server_plugins() -> None:
    """Test registering multiple control server plugins."""

    class TestControlServer1:
        def __init__(self, pilot: ProcessPilot) -> None:
            self.pilot = pilot

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class TestControlServer2:
        def __init__(self, pilot: ProcessPilot) -> None:
            self.pilot = pilot

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class ControlPlugin1(Plugin):
        def get_control_servers(self) -> dict[str, ControlServerType]:
            return {"test1": lambda pilot: TestControlServer1(pilot)}

    class ControlPlugin2(Plugin):
        def get_control_servers(self) -> dict[str, ControlServerType]:
            return {"test2": lambda pilot: TestControlServer2(pilot)}

    manifest = ProcessManifest(processes=[], control_server="test2")

    pilot = ProcessPilot(manifest)
    pilot.register_plugins([ControlPlugin1(), ControlPlugin2()])

    assert pilot._control_server is not None
    assert isinstance(pilot._control_server, TestControlServer2)


def test_control_server_restart_processes(mocker: MockerFixture) -> None:
    """Test control server restart_processes functionality."""

    class TestControlServer:
        def __init__(self, pilot: ProcessPilot) -> None:
            self.pilot = pilot

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def restart_processes(self, process_names: list[str]) -> None:
            self.pilot.restart_processes(process_names)

    class ControlPlugin(Plugin):
        def get_control_servers(self) -> dict[str, ControlServerType]:
            return {"test": lambda pilot: TestControlServer(pilot)}

    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    manifest = ProcessManifest(
        processes=[Process(name="test1", path=Path("/test/path1")), Process(name="test2", path=Path("/test/path2"))],
        control_server="test",
    )

    pilot = ProcessPilot(manifest)
    plugin = ControlPlugin()
    pilot.register_plugins([plugin])

    mock_restart = mocker.patch.object(pilot, "restart_processes")

    assert pilot._control_server is not None
    pilot.restart_processes(["test1", "test2"])

    mock_restart.assert_called_once_with(["test1", "test2"])
