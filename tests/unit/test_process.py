import os  # noqa: INP001
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from unittest import mock

import psutil
import pytest
from pytest_mock import MockerFixture

from process_pilot.pilot import ProcessPilot
from process_pilot.process import Process, ProcessManifest, ProcessRuntimeInfo, ProcessState, ProcessStatus


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
def test_can_load_json() -> None:
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "examples" / "services.json")
    sleep_location = shutil.which("sleep")

    if not sleep_location:
        pytest.fail("'Sleep' not found in path.")

    assert len(manifest.processes) == 4
    assert manifest.processes[0].args == ["15"]
    assert manifest.processes[0].path == Path(sleep_location)
    assert manifest.processes[0].timeout == 3.0


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
def test_can_load_yaml() -> None:
    manifest = ProcessManifest.from_yaml(Path(__file__).parent.parent / "examples" / "services.yaml")
    sleep_location = shutil.which("sleep")

    if not sleep_location:
        pytest.fail("'Sleep' not found in path.")
    assert len(manifest.processes) == 1

    assert manifest.processes[0].args == ["5"]
    assert manifest.processes[0].path == Path(sleep_location)
    assert manifest.processes[0].timeout == 1.0


@pytest.fixture
def mock_process() -> subprocess.Popen[str]:
    """Fixture to mock a subprocess.Popen[str] object."""
    mock_process: subprocess.Popen[str] = mock.MagicMock(spec=subprocess.Popen[str])
    mock_process.poll.return_value = None  # type: ignore[attr-defined]
    return mock_process


@pytest.fixture
def mock_process_with_exit() -> subprocess.Popen[str]:
    """Fixture to mock a subprocess.Popen[str] object that has exited."""
    mock_process: subprocess.Popen[str] = mock.MagicMock(spec=subprocess.Popen[str])
    mock_process.poll.return_value = 0  # type: ignore[attr-defined]
    mock_process.returncode = 0  # Simulate successful exit code
    return mock_process


def test_process_initialization() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        args=["--arg1", "value1"],
        timeout=10.0,
        shutdown_strategy="restart",
        dependencies=["dep1", "dep2"],
    )

    assert process.name == "test_process"
    assert process.path == Path("/mock/path/to/executable")
    assert process.args == ["--arg1", "value1"]
    assert process.timeout == 10.0
    assert process.shutdown_strategy == "restart"
    assert process.dependencies == ["dep1", "dep2"]


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
def test_process_command_property() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        args=["--arg1", "value1"],
    )

    assert process.command == ["/mock/path/to/executable", "--arg1", "value1"]


def test_process_record_process_stats(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
    )

    mock_psutil_process = mocker.patch("psutil.Process")
    mock_psutil_instance = mock_psutil_process.return_value
    mock_psutil_instance.memory_info.return_value = mock.Mock(rss=1048576)  # 1 MB
    mock_psutil_instance.cpu_percent.return_value = 10.0

    process.record_process_stats(1234)

    assert process._runtime_info.memory_usage_mb == 1.0
    assert process._runtime_info.cpu_usage_percent == 10.0


def test_process_record_process_stats_no_such_process(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
    )

    _ = mocker.patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=1234))

    process.record_process_stats(1234)

    assert process._runtime_info.memory_usage_mb == 0.0
    assert process._runtime_info.cpu_usage_percent == 0.0


def test_process_manifest_from_json_invalid_path() -> None:
    mock_json_path: Path = Path("/invalid/path/to/manifest.json")

    with pytest.raises(FileNotFoundError):
        ProcessManifest.from_json(mock_json_path)


def test_process_manifest_from_yaml_invalid_path() -> None:
    mock_yaml_path: Path = Path("/invalid/path/to/manifest.yaml")

    with pytest.raises(FileNotFoundError):
        ProcessManifest.from_yaml(mock_yaml_path)


def test_process_pilot_initialization_with_invalid_manifest() -> None:
    invalid_manifest_data = {
        "processes": [
            {
                "name": "test_process",
                "path": "mock/path/to/service",
                "args": ["--arg1", "value1"],
                "timeout": 10.0,
                "shutdown_strategy": "invalid_strategy",
            },
        ],
    }

    with pytest.raises(ValueError):  # noqa: PT011
        ProcessManifest(**invalid_manifest_data)  # type: ignore[arg-type]


def test_process_pilot_start_with_no_processes() -> None:
    empty_manifest = ProcessManifest(processes=[])
    pilot = ProcessPilot(manifest=empty_manifest)

    with pytest.raises(RuntimeError, match="No processes to start"):
        pilot.start()


def test_process_manifest_circular_dependencies(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test", "dependencies": ["process2"]},
            {"name": "process2", "path": "test", "dependencies": ["process1"]},
        ],
    }

    with pytest.raises(ValueError, match="Circular dependency detected"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_manifest_duplicate_names(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {"processes": [{"name": "process1", "path": "test"}, {"name": "process1", "path": "test"}]}

    with pytest.raises(ValueError, match="Duplicate process name found"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_manifest_missing_dependency(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {"processes": [{"name": "process1", "path": "test", "dependencies": ["nonexistent"]}]}

    with pytest.raises(ValueError, match="Dependency .* not found"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_runtime_info() -> None:
    info = ProcessRuntimeInfo()

    # Test initial values
    assert info.memory_usage_mb == 0.0
    assert info.cpu_usage_percent == 0.0
    assert info.max_memory_usage_mb == 0.0
    assert info.max_cpu_usage == 0.0

    # Test setting new values
    info.memory_usage_mb = 100.0
    info.cpu_usage_percent = 50.0
    assert info.memory_usage_mb == 100.0
    assert info.cpu_usage_percent == 50.0

    # Test max values update
    info.memory_usage_mb = 50.0  # Lower value
    info.cpu_usage_percent = 75.0  # Higher value
    assert info.max_memory_usage_mb == 100.0  # Should keep previous max
    assert info.max_cpu_usage == 75.0  # Should update to new max


def test_process_manifest_dependency_ordering(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {
        "processes": [
            {"name": "process3", "path": "test", "dependencies": ["process2"]},
            {"name": "process1", "path": "test"},
            {"name": "process2", "path": "test", "dependencies": ["process1"]},
        ],
    }

    manifest = ProcessManifest(**manifest_data)  # type: ignore[arg-type]

    # Verify correct ordering
    process_names = [p.name for p in manifest.processes]
    assert process_names == ["process1", "process2", "process3"]


def test_process_stats_permission_error(mocker: MockerFixture) -> None:
    process = Process(
        name="test_process",
        path=Path("/test/executable"),
    )

    mock_psutil = mocker.patch("psutil.Process")
    mock_psutil.side_effect = psutil.AccessDenied

    with pytest.raises(psutil.AccessDenied):
        process.record_process_stats(1234)

    assert process._runtime_info.memory_usage_mb == 0.0
    assert process._runtime_info.cpu_usage_percent == 0.0


def test_process_environment_variables(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(name="test_env", path=Path("/test/path"), env={"TEST_VAR": "test_value"}),
        ],
    )

    pilot = ProcessPilot(manifest=manifest)
    mock_popen = mocker.patch("subprocess.Popen")

    pilot._initialize_processes()

    # Get the env dict that was passed to Popen
    called_env = mock_popen.call_args[1]["env"]

    # Verify our env var was included
    assert called_env["TEST_VAR"] == "test_value"

    # Verify we preserved parent env
    assert "PATH" in called_env


def test_process_manifest_validate_ready_config(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {
        "processes": [
            {
                "name": "process1",
                "path": "test",
                "ready_strategy": "file",
                "ready_params": {},
            },
            {
                "name": "process2",
                "path": "test",
                "ready_strategy": "tcp",
                "ready_params": {},
            },
        ],
    }

    with pytest.raises(ValueError, match="File and pipe ready strategies require 'path' parameter: process1"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]

    manifest_data["processes"][0]["ready_params"]["path"] = "/tmp/ready.txt"  # type: ignore[index]
    with pytest.raises(ValueError, match="TCP ready strategy requires 'port' parameter: process2"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_pilot_initialization(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(name="test_process", path=Path("/test/executable")),
        ],
    )

    pilot = ProcessPilot(manifest)
    assert pilot._manifest == manifest
    assert pilot._process_poll_interval_secs == 0.1
    assert pilot._ready_check_interval_secs == 0.1
    assert pilot._running_processes == []
    assert not pilot._shutting_down


def test_process_pilot_start(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(name="test_process", path=Path("/test/executable")),
        ],
    )

    pilot = ProcessPilot(manifest)
    mock_initialize = mocker.patch.object(pilot, "_initialize_processes")
    mock_process_loop = mocker.patch.object(pilot, "_process_loop", side_effect=pilot.stop)

    pilot.start()

    mock_initialize.assert_called_once()
    mock_process_loop.assert_called_once()


def test_process_pilot_initialize_processes(mocker: MockerFixture) -> None:
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(name="test_process", path=Path("/test/executable")),
        ],
    )

    pilot = ProcessPilot(manifest)
    mock_popen = mocker.patch("subprocess.Popen")
    mock_execute_hooks = mocker.patch.object(ProcessPilot, "execute_lifecycle_hooks")

    pilot._initialize_processes()

    mock_popen.assert_called()
    assert mock_execute_hooks.call_args_list[0].kwargs["process"] == manifest.processes[0]
    assert mock_execute_hooks.call_args_list[0].kwargs["hook_type"] == "pre_start"

    assert mock_execute_hooks.call_args_list[1].kwargs["process"] == manifest.processes[0]
    assert mock_execute_hooks.call_args_list[1].kwargs["hook_type"] == "post_start"


def test_process_pilot_double_start(mocker: MockerFixture) -> None:
    """Test starting ProcessPilot when it's already running."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path"))])
    pilot = ProcessPilot(manifest)
    pilot.start()

    with pytest.raises(RuntimeError, match="ProcessPilot is already running"):
        pilot.start()


def test_process_pilot_stop_not_running() -> None:
    """Test stopping ProcessPilot when it's not running."""
    pilot = ProcessPilot(ProcessManifest(processes=[]))
    pilot.stop()  # Should not raise


def test_process_pilot_process_environment_inheritance(mocker: MockerFixture) -> None:
    """Test that processes inherit environment variables correctly."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path"), env={"TEST_VAR": "override"})])

    with mock.patch.dict(os.environ, {"TEST_VAR": "original", "PATH": "/usr/bin"}):
        pilot = ProcessPilot(manifest)
        mock_popen = mocker.patch("subprocess.Popen")
        pilot._initialize_processes()

        env = mock_popen.call_args[1]["env"]
        assert env["TEST_VAR"] == "override"
        assert env["PATH"] == "/usr/bin"


def test_process_pilot_subprocess_creation_failure(mocker: MockerFixture) -> None:
    """Test handling of subprocess creation failure."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/nonexistent/path"))])
    pilot = ProcessPilot(manifest)

    _ = mocker.patch("subprocess.Popen", side_effect=FileNotFoundError("No such file"))

    with pytest.raises(FileNotFoundError, match="No such file"):
        pilot._initialize_processes()


def test_process_pilot_ready_check_timeout(mocker: MockerFixture) -> None:
    """Test handling of ready check timeout."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="test",
                path=Path("/test/path"),
                ready_strategy="tcp",
                ready_params={"port": 8080},
                ready_timeout_sec=0.1,
            ),
        ],
    )

    pilot = ProcessPilot(manifest)
    mock_popen = mocker.patch("subprocess.Popen")
    mock_popen.return_value.poll.return_value = None  # Mock the process as running

    with pytest.raises(RuntimeError, match="failed to signal ready"):
        pilot._initialize_processes()


def test_process_pilot_restart_processes(mocker: MockerFixture) -> None:
    """Test restarting specific processes."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(name="test1", path=Path("/test/path1")),
            Process(name="test2", path=Path("/test/path2")),
        ],
    )

    pilot = ProcessPilot(manifest)

    # Mock initial processes
    mock_popen1 = mocker.Mock()
    mock_popen1.poll.return_value = None
    mock_popen1.pid = 1234

    mock_popen2 = mocker.Mock()
    mock_popen2.poll.return_value = None
    mock_popen2.pid = 5678

    pilot._running_processes = [(manifest.processes[0], mock_popen1), (manifest.processes[1], mock_popen2)]

    # Mock new process creation
    mock_new_popen = mocker.patch("subprocess.Popen")
    mock_new_popen.return_value.poll.return_value = None

    # Test restarting one process
    mock_terminate_process_tree = mocker.patch.object(pilot, "_terminate_process_tree")

    pilot.restart_processes(["test1"])

    mock_terminate_process_tree.assert_called_once()


def test_process_pilot_restart_invalid_process(mocker: MockerFixture) -> None:
    """Test restarting a non-existent process."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path"))])

    pilot = ProcessPilot(manifest)

    with pytest.raises(ValueError, match="Process 'invalid' not found"):
        pilot.restart_processes(["invalid"])


def test_set_process_affinity_linux(mocker: MockerFixture) -> None:
    """Test setting process affinity."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path"))])
    pilot = ProcessPilot(manifest)

    mock_process = mocker.Mock(spec=subprocess.Popen)
    mock_process.pid = 1234

    mock_psutil_process = mocker.patch("psutil.Process")
    mock_psutil_instance = mock_psutil_process.return_value

    mocker.patch("platform.system", return_value="Linux")
    pilot.set_process_affinity(mock_process, [0, 1])

    mock_psutil_instance.cpu_affinity.assert_called_once_with([0, 1])


def test_set_process_affinity_macosx(mocker: MockerFixture) -> None:
    """Test setting process affinity."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path"))])
    pilot = ProcessPilot(manifest)

    mock_process = mocker.Mock(spec=subprocess.Popen)
    mock_process.pid = 1234

    mock_psutil_process = mocker.patch("psutil.Process")
    mock_psutil_instance = mock_psutil_process.return_value

    mocker.patch("platform.system", return_value="Darwin")
    pilot.set_process_affinity(mock_process, [0, 1])

    mock_psutil_instance.cpu_affinity.assert_not_called()


def test_validate_cpu_affinity(mocker: MockerFixture) -> None:
    """Test validating CPU affinity."""
    mocker.patch("psutil.cpu_count", return_value=4)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)

    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test", "affinity": [0, 1]},
            {"name": "process2", "path": "test", "affinity": [2, 3]},
        ],
    }
    manifest = ProcessManifest(**manifest_data)  # type: ignore[arg-type]
    assert manifest.validate_cpu_affinity() == manifest  # type: ignore[operator]

    manifest_data["processes"][0]["affinity"] = [4]  # type: ignore[index, unused-ignore]
    with pytest.raises(ValueError, match="Affinity core 4 is out of range for process: process1"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]

    manifest_data["processes"][0]["affinity"] = [-1]  # type: ignore[index, unused-ignore]
    with pytest.raises(ValueError, match="Affinity values must be between 0 and 3"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_resolve_paths_nominal(mocker: MockerFixture) -> None:
    """Test resolve_paths with valid paths."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/executable"))])
    assert manifest.processes[0].path == Path("/test/path/executable").resolve()


def test_resolve_paths_with_wildcard(mocker: MockerFixture) -> None:
    """Test resolve_paths with wildcard in path."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.rglob", return_value=[Path("/test/path/executable")])
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/*"))])
    assert manifest.processes[0].path == Path("/test/path/executable").resolve()


def test_resolve_paths_no_wildcard_match(mocker: MockerFixture) -> None:
    """Test resolve_paths with no matches for wildcard."""
    mocker.patch("pathlib.Path.rglob", return_value=[])
    mocker.patch("pathlib.Path.exists", return_value=True)
    with pytest.raises(ValueError, match="No matches found for wildcard path"):
        _ = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/*"))])


def test_resolve_paths_executable_not_found(mocker: MockerFixture) -> None:
    """Test resolve_paths with non-existent executable."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=False)
    with pytest.raises(ValueError, match="Executable not found"):
        _ = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/executable"))])


def test_resolve_paths_executable_found_but_not_a_file(mocker: MockerFixture) -> None:
    """Test resolve_paths with non-existent executable."""
    mocker.patch("pathlib.Path.is_file", return_value=False)
    mocker.patch("pathlib.Path.exists", return_value=True)
    with pytest.raises(ValueError, match="Executable not found"):
        _ = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/executable"))])


def test_resolve_paths_windows_style(mocker: MockerFixture) -> None:
    """Test resolve_paths with Windows style path separators."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("C:\\test\\path\\executable"))])
    assert manifest.processes[0].path == Path("C:\\test\\path\\executable").resolve()


def test_resolve_paths_unix_style(mocker: MockerFixture) -> None:
    """Test resolve_paths with Unix style path separators."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(processes=[Process(name="test", path=Path("/test/path/executable"))])
    assert manifest.processes[0].path == Path("/test/path/executable").resolve()


def test_set_working_directory_default(mocker: MockerFixture) -> None:
    """Test setting the working directory to the executable's parent directory if not provided."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test/executable"},
        ],
    }
    manifest = ProcessManifest(**manifest_data)  # type: ignore[arg-type]
    assert manifest.processes[0].working_directory == Path("test").resolve()


def test_set_working_directory_provided(mocker: MockerFixture) -> None:
    """Test setting the working directory if provided."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_dir", return_value=True)
    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test/executable", "working_directory": "custom/dir"},
        ],
    }
    manifest = ProcessManifest(**manifest_data)  # type: ignore[arg-type]
    assert manifest.processes[0].working_directory == Path("custom/dir")


def test_set_working_directory_invalid(mocker: MockerFixture) -> None:
    """Test raising an error if the provided working directory does not exist."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_dir", return_value=False)
    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test/executable", "working_directory": "invalid/dir"},
        ],
    }

    with pytest.raises(ValueError, match="Working directory does not exist"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


@pytest.fixture
def sample_process_manifest(mocker: MockerFixture) -> ProcessManifest:
    """Fixture to provide a sample process manifest."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_dir", return_value=False)
    process_data = {
        "processes": [
            {
                "name": "test_process",
                "path": "mock/path/to/service",
                "args": ["--arg1", "value1"],
                "timeout": 10.0,
                "shutdown_strategy": "restart",
            },
            {
                "name": "test_process_2",
                "path": "mock/path/to/service2",
                "args": [],
                "timeout": 5.0,
                "shutdown_strategy": "do_not_restart",
            },
        ],
    }
    return ProcessManifest(**process_data)  # type: ignore[arg-type]


@pytest.fixture
def pilot(sample_process_manifest: ProcessManifest) -> ProcessPilot:
    """Fixture to provide a ProcessPilot instance."""
    return ProcessPilot(manifest=sample_process_manifest)


def test_get_manifest_processes(pilot: ProcessPilot) -> None:
    processes = pilot.get_manifest_processes()
    assert len(processes) == 2
    assert processes[0].name == "test_process"
    assert processes[1].name == "test_process_2"


def test_get_running_process(pilot: ProcessPilot, mocker: MockerFixture) -> None:
    mock_popen = mocker.Mock(spec=subprocess.Popen)
    mock_popen.pid = 1234
    pilot._manifest.processes[0]._pid = 1234
    pilot._running_processes.append((pilot._manifest.processes[0], mock_popen))

    process = pilot.get_running_process(1234)
    assert process is not None
    assert isinstance(process, ProcessStatus)
    assert process.pid == 1234

    process = pilot.get_running_process("test_process")
    assert process is not None
    assert isinstance(process, ProcessStatus)
    assert process.pid == 1234

    process = pilot.get_running_process("nonexistent")
    assert process is None


def test_get_process_by_name(pilot: ProcessPilot) -> None:
    process = pilot.get_process_by_name("test_process")
    assert process is not None
    assert process.name == "test_process"

    process = pilot.get_process_by_name("nonexistent")
    assert process is None


def test_start_process(pilot: ProcessPilot, mocker: MockerFixture) -> None:
    mock_popen = mocker.patch("subprocess.Popen")
    pilot.start_process("test_process")
    mock_popen.assert_called()

    with pytest.raises(ValueError, match="Process 'nonexistent' not found"):
        pilot.start_process("nonexistent")


def test_stop_process(pilot: ProcessPilot, mocker: MockerFixture) -> None:
    mock_popen = mocker.Mock(spec=subprocess.Popen)
    mock_popen.pid = 1234
    mock_popen.returncode = 0
    pilot._running_processes.append((pilot._manifest.processes[0], mock_popen))

    mock_terminate_process_tree = mocker.patch.object(pilot, "_terminate_process_tree")
    pilot.stop_process("test_process")
    mock_terminate_process_tree.assert_called_once()

    with pytest.raises(ValueError, match="Process 'nonexistent' not found"):
        pilot.stop_process("nonexistent")


def test_restart_processes(pilot: ProcessPilot, mocker: MockerFixture) -> None:
    mock_popen = mocker.Mock(spec=subprocess.Popen)
    mock_popen.pid = 1234
    mock_popen.returncode = 0
    pilot._running_processes.append((pilot._manifest.processes[0], mock_popen))

    mock_new_popen = mocker.patch("subprocess.Popen")
    mock_terminate_process_tree = mocker.patch.object(pilot, "_terminate_process_tree")
    pilot.restart_processes(["test_process"])
    mock_terminate_process_tree.assert_called_once()
    mock_new_popen.assert_called_once()

    with pytest.raises(ValueError, match="Process 'nonexistent' not found"):
        pilot.restart_processes(["nonexistent"])


def test_update_status_basic() -> None:
    """Test basic status update."""
    process = Process(name="test", path=Path("/test/path"))
    process.update_status(ProcessState.RUNNING)
    assert process._status == ProcessState.RUNNING


def test_update_status_stopped_resets_pid() -> None:
    """Test that STOPPED state resets PID to 0."""
    process = Process(name="test", path=Path("/test/path"))
    process._pid = 1234
    process.update_status(ProcessState.STOPPED)
    assert process._pid == 0


def test_update_status_running_resets_return_code() -> None:
    """Test that RUNNING state resets return code to -1."""
    process = Process(name="test", path=Path("/test/path"))
    process._return_code = 0
    process.update_status(ProcessState.RUNNING)
    assert process._return_code == -1


def test_update_status_pid_when_zero() -> None:
    """Test setting PID when current PID is 0."""
    process = Process(name="test", path=Path("/test/path"))
    process.update_status(ProcessState.RUNNING, pid=1234)
    assert process._pid == 1234


def test_update_status_pid_when_set() -> None:
    """Test that PID is not updated when already set."""
    process = Process(name="test", path=Path("/test/path"))
    process._pid = 1234
    process.update_status(ProcessState.RUNNING, pid=5678)
    assert process._pid == 1234


def test_update_status_with_return_code() -> None:
    """Test setting return code."""
    process = Process(name="test", path=Path("/test/path"))
    process.update_status(ProcessState.STOPPED, return_code=1)
    assert process._return_code == 1


def test_update_status_with_pid_and_return_code() -> None:
    """Test setting both PID and return code."""
    process = Process(name="test", path=Path("/test/path"))
    process.update_status(ProcessState.RUNNING, pid=1234, return_code=0)
    assert process._pid == 1234
    assert process._return_code == 0


@pytest.fixture
def mock_sub_process() -> mock.MagicMock:
    """Create a mock subprocess.Popen instance."""
    process = mock.MagicMock(spec=subprocess.Popen[str])
    process.pid = 12345
    return process


@pytest.fixture
def mock_psutil_process() -> mock.MagicMock:
    """Create a mock psutil.Process instance."""
    process = mock.MagicMock(spec=psutil.Process)
    process.children.return_value = []
    return process


# Skip if Python 3.10
@pytest.mark.skipif(
    sys.version_info[:2] == (3, 10), reason="Python 3.10 has more strict type checking with subprocess.Popen"
)
def test_terminate_already_terminated_process(pilot: ProcessPilot, mock_sub_process: mock.MagicMock) -> None:
    """Test terminating an already terminated process."""
    mock_sub_process.pid = None
    pilot._terminate_process_tree(mock_sub_process)
    mock_sub_process.terminate.assert_not_called()


@mock.patch("platform.system", return_value="Windows")
@mock.patch("psutil.Process")
def test_terminate_windows_process_tree(
    mock_psutil_proc: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    with mock.patch("psutil.wait_procs") as mock_psutil_wait_procs:
        child_process = mock.MagicMock()
        mock_psutil_instance = mock_psutil_proc.return_value
        mock_psutil_instance.children.return_value = [child_process]

        pilot._terminate_process_tree(mock_sub_process)

        # Verify children were terminated
        child_process.terminate.assert_called_once()

        # Verify parent was terminated
        mock_sub_process.terminate.assert_called_once()

        # Ensure that wait_procs was called
        mock_psutil_wait_procs.assert_called_once()


@mock.patch("platform.system", return_value="Linux")
@mock.patch("os.killpg")
@mock.patch("os.getpgid")
@mock.patch("psutil.Process")
def test_terminate_unix_process_group(  # noqa: PLR0913
    mock_psutil_proc: mock.MagicMock,  # noqa: ARG001
    mock_getpgid: mock.MagicMock,
    mock_killpg: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test Unix-specific process group termination."""
    mock_getpgid.return_value = 12345

    pilot._terminate_process_tree(mock_sub_process, timeout=1.0)

    # Verify SIGTERM was sent to process group
    mock_killpg.assert_called_with(12345, signal.SIGTERM)
    mock_sub_process.wait.assert_called_once_with(timeout=1.0)


@mock.patch("platform.system", return_value="Linux")
@mock.patch("os.killpg")
@mock.patch("os.getpgid")
@mock.patch("psutil.Process")
def test_terminate_unix_process_timeout(  # noqa: PLR0913
    mock_psutil_proc: mock.MagicMock,  # noqa: ARG001
    mock_getpgid: mock.MagicMock,
    mock_killpg: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test Unix process termination with timeout."""
    mock_getpgid.return_value = 12345
    mock_sub_process.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=1.0)

    pilot._terminate_process_tree(mock_sub_process, timeout=1.0)

    # Verify SIGKILL was sent after timeout
    assert mock_killpg.call_count == 2
    mock_killpg.assert_any_call(12345, signal.SIGTERM)
    mock_killpg.assert_any_call(12345, signal.SIGKILL)


@mock.patch("platform.system", return_value="Linux")
@mock.patch("psutil.Process")
def test_handle_no_such_process(
    mock_psutil_proc: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test handling of NoSuchProcess exception."""
    mock_psutil_proc.side_effect = psutil.NoSuchProcess(pid=12345)

    # Should not raise an exception
    pilot._terminate_process_tree(mock_sub_process)


@mock.patch("platform.system", return_value="Linux")
@mock.patch("os.killpg")
@mock.patch("os.getpgid")
@mock.patch("psutil.Process")
def test_handle_process_lookup_error(  # noqa: PLR0913
    mock_psutil_proc: mock.MagicMock,  # noqa: ARG001
    mock_getpgid: mock.MagicMock,
    mock_killpg: mock.MagicMock,  # noqa: ARG001
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test handling of ProcessLookupError."""
    mock_getpgid.side_effect = ProcessLookupError()

    # Should not raise an exception
    pilot._terminate_process_tree(mock_sub_process)


@mock.patch("platform.system", return_value="Linux")
@mock.patch("psutil.Process")
def test_handle_generic_exception(
    mock_psutil_proc: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test handling of generic exceptions."""
    mock_psutil_proc.side_effect = Exception("Unexpected error")

    # Should not raise an exception
    pilot._terminate_process_tree(mock_sub_process)


@mock.patch("platform.system", return_value="Windows")
@mock.patch("psutil.Process")
def test_windows_force_kill_after_timeout(
    mock_psutil_proc: mock.MagicMock,
    mock_platform: mock.MagicMock,  # noqa: ARG001
    pilot: ProcessPilot,
    mock_sub_process: mock.MagicMock,
) -> None:
    """Test Windows force kill after timeout."""
    with mock.patch("psutil.wait_procs") as mock_psutil_wait_procs:
        child_process = mock.MagicMock()
        mock_psutil_instance = mock_psutil_proc.return_value
        mock_psutil_instance.children.return_value = [child_process]
        mock_psutil_wait_procs.return_value = ([], [child_process])

        pilot._terminate_process_tree(mock_sub_process, timeout=1.0)

        # Verify children were terminated
        child_process.terminate.assert_called_once()

        # Verify parent was terminated
        mock_sub_process.terminate.assert_called_once()

        # Verify force kill was called after timeout
        child_process.kill.assert_called_once()
