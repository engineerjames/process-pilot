import subprocess  # noqa: INP001
from pathlib import Path
from unittest import mock

import psutil
import pytest
from pytest_mock import MockerFixture

from process_pilot.pilot import ProcessPilot
from process_pilot.process import Process, ProcessManifest, ProcessRuntimeInfo


def test_can_load_json() -> None:
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "examples" / "services.json")

    assert len(manifest.processes) == 4
    assert manifest.processes[0].args == ["15"]
    assert manifest.processes[0].path == Path("sleep")
    assert manifest.processes[0].timeout == 3.0


def test_can_load_yaml() -> None:
    manifest = ProcessManifest.from_yaml(Path(__file__).parent.parent / "examples" / "services.yaml")

    assert len(manifest.processes) == 1
    assert manifest.processes[0].args == ["5"]
    assert manifest.processes[0].path == Path("sleep")
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


@pytest.fixture
def sample_process_manifest() -> ProcessManifest:
    """Fixture to provide a sample process manifest."""
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
    assert process.hook == {}


def test_process_command_property() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
        args=["--arg1", "value1"],
    )

    assert process.command == ["/mock/path/to/executable", "--arg1", "value1"]


def test_process_register_hook() -> None:
    process = Process(
        name="test_process",
        path=Path("/mock/path/to/executable"),
    )

    def mock_hook(process: Process, popen: subprocess.Popen[str] | None) -> None:
        pass

    process.register_hook("pre_start", mock_hook)
    assert len(process.hook["pre_start"]) == 1
    assert process.hook["pre_start"][0] == mock_hook

    process.register_hook("pre_start", [mock_hook, mock_hook])
    assert len(process.hook["pre_start"]) == 3


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


def test_process_manifest_circular_dependencies() -> None:
    manifest_data = {
        "processes": [
            {"name": "process1", "path": "test", "dependencies": ["process2"]},
            {"name": "process2", "path": "test", "dependencies": ["process1"]},
        ],
    }

    with pytest.raises(ValueError, match="Circular dependency detected"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_manifest_duplicate_names() -> None:
    manifest_data = {"processes": [{"name": "process1", "path": "test"}, {"name": "process1", "path": "test"}]}

    with pytest.raises(ValueError, match="Duplicate process name found"):
        ProcessManifest(**manifest_data)  # type: ignore[arg-type]


def test_process_manifest_missing_dependency() -> None:
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


def test_process_hooks_execution_order() -> None:
    process = Process(name="test_process", path=Path("/test/path"))

    execution_order = []

    def hook1(_: Process, _p: subprocess.Popen[str] | None) -> None:
        execution_order.append("hook1")

    def hook2(_: Process, _p: subprocess.Popen[str] | None) -> None:
        execution_order.append("hook2")

    process.register_hook("pre_start", [hook1, hook2])

    # Mock ProcessPilot._execute_hooks to actually call the hooks
    ProcessPilot._execute_hooks(
        process=process,
        popen=None,
        hook_type="pre_start",
    )

    assert execution_order == ["hook1", "hook2"]


def test_process_manifest_dependency_ordering() -> None:
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


def test_register_invalid_hook_type() -> None:
    process = Process(
        name="test_process",
        path=Path("/test/executable"),
    )

    def mock_hook(_: Process) -> None:
        pass

    with pytest.raises(ValueError, match="Invalid hook type"):
        process.register_hook("invalid_hook_type", mock_hook)  # type:ignore[arg-type]


def test_failing_hook_execution() -> None:
    process = Process(
        name="test_process",
        path=Path("/test/executable"),
    )

    def failing_hook(_: Process, _p: subprocess.Popen[str] | None) -> None:
        error_message = "Hook failed"
        raise RuntimeError(error_message)

    process.register_hook("pre_start", failing_hook)

    with pytest.raises(RuntimeError, match="Hook failed"):
        ProcessPilot._execute_hooks(
            process=process,
            popen=None,
            hook_type="pre_start",
        )


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


def test_process_manifest_validate_ready_config() -> None:
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


def test_process_pilot_initialization() -> None:
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
    manifest = ProcessManifest(
        processes=[
            Process(name="test_process", path=Path("/test/executable")),
        ],
    )

    pilot = ProcessPilot(manifest)
    mock_popen = mocker.patch("subprocess.Popen")
    mock_execute_hooks = mocker.patch.object(ProcessPilot, "_execute_hooks")

    pilot._initialize_processes()

    mock_popen.assert_called_once_with(
        ["/test/executable"],
        encoding="utf-8",
        env=mocker.ANY,
    )
    assert mock_execute_hooks.call_args_list[0].kwargs["process"] == manifest.processes[0]
    assert mock_execute_hooks.call_args_list[0].kwargs["hook_type"] == "pre_start"

    assert mock_execute_hooks.call_args_list[1].kwargs["process"] == manifest.processes[0]
    assert mock_execute_hooks.call_args_list[1].kwargs["hook_type"] == "post_start"


def test_resolve_relative_paths() -> None:
    manifest_path = Path("/mock/manifest/dir/manifest.yaml")
    process = Process(
        name="test_process",
        path=Path("relative/path/to/executable"),
        args=["arg1", "relative/path/to/arg2.txt"],
    )
    manifest = ProcessManifest(processes=[process])
    manifest._resolve_paths_relative_to_manifest(manifest_path)

    assert process.path == Path("/mock/manifest/dir/relative/path/to/executable")
    assert process.args == ["arg1", "/mock/manifest/dir/relative/path/to/arg2.txt"]


def test_resolve_absolute_paths() -> None:
    manifest_path = Path("/mock/manifest/dir/manifest.yaml")
    process = Process(
        name="test_process",
        path=Path("/absolute/path/to/executable"),
        args=["arg1", "/absolute/path/to/arg2.txt"],
    )
    manifest = ProcessManifest(processes=[process])
    manifest._resolve_paths_relative_to_manifest(manifest_path)

    assert process.path == Path("/absolute/path/to/executable")
    assert process.args == ["arg1", "/absolute/path/to/arg2.txt"]


def test_resolve_python_path() -> None:
    manifest_path = Path("/mock/manifest/dir/manifest.yaml")
    process = Process(name="test_process", path=Path("python"), args=["arg1", "relative/path/to/arg2.txt"])
    manifest = ProcessManifest(processes=[process])
    manifest._resolve_paths_relative_to_manifest(manifest_path)

    assert process.path == Path("python")
    assert process.args == ["arg1", "/mock/manifest/dir/relative/path/to/arg2.txt"]


def test_resolve_argument_paths() -> None:
    manifest_path = Path("/mock/manifest/dir/manifest.yaml")
    process = Process(
        name="test_process",
        path=Path("relative/path/to/executable"),
        args=["arg1", "relative/path/to/arg2.txt", "arg3"],
    )
    manifest = ProcessManifest(processes=[process])
    manifest._resolve_paths_relative_to_manifest(manifest_path)

    assert process.path == Path("/mock/manifest/dir/relative/path/to/executable")
    assert process.args == ["arg1", "/mock/manifest/dir/relative/path/to/arg2.txt", "arg3"]
