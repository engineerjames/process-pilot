import subprocess
from pathlib import Path
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from process_pilot.process import ProcessManifest, ProcessPilot


def test_can_load_json() -> None:
    manifest = ProcessManifest.from_json(Path(__file__).parent / "examples" / "services.json")

    assert len(manifest.processes) == 1
    assert manifest.processes[0].args == ["5"]
    assert manifest.processes[0].path == Path("sleep")
    assert manifest.processes[0].timeout == 3.0


def test_can_load_yaml() -> None:
    manifest = ProcessManifest.from_yaml(Path(__file__).parent / "examples" / "services.yaml")

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


# Test case for ProcessManifest loading from JSON
def test_process_manifest_from_json(mocker: MockerFixture) -> None:
    mock_json_path: Path = Path("/mock/path/to/manifest.json")
    mock_json_data: str = '{"processes":[{"name": "test", "path":"mock/path/to/service"}]}'

    mocker.patch.object(Path, "open", mocker.mock_open(read_data=mock_json_data))
    manifest: ProcessManifest = ProcessManifest.from_json(mock_json_path)

    assert len(manifest.processes) == 1
    assert manifest.processes[0].path == Path("mock/path/to/service")


# Test case for ProcessManifest loading from YAML
def test_process_manifest_from_yaml(mocker: MockerFixture) -> None:
    mock_yaml_path: Path = Path("/mock/path/to/manifest.yaml")
    mock_yaml_data: str = "processes:\n  - path: mock/path/to/service\n\n    name: test"

    # Patch Path.open() instead of builtins.open to mock file reading
    mocker.patch.object(Path, "open", mocker.mock_open(read_data=mock_yaml_data))

    # Load the manifest using the patched Path.open
    manifest: ProcessManifest = ProcessManifest.from_yaml(mock_yaml_path)

    # Assert that the data is correctly parsed
    assert len(manifest.processes) == 1
    assert manifest.processes[0].path == Path("mock/path/to/service")


# Test case for initializing ProcessPilot with a mock manifest
def test_process_pilot_initialization(sample_process_manifest: ProcessManifest) -> None:
    pilot: ProcessPilot = ProcessPilot(manifest=sample_process_manifest)
    assert len(pilot._manifest.processes) == 2
    assert pilot._poll_interval == 0.1  # Default value
