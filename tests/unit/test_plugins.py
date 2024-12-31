import os
import socket  # noqa: INP001
import sys
from pathlib import Path, PosixPath
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from process_pilot.plugins.file_ready import FileReadyPlugin
from process_pilot.plugins.pipe_ready import PipeReadyPlugin
from process_pilot.plugins.tcp_ready import TCPReadyPlugin
from process_pilot.process import Process


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
    mock_unlink = mocker.patch("pathlib.Path.unlink")

    plugin = PipeReadyPlugin()
    assert plugin._wait_pipe_ready_unix(process, 0.1)
    mock_os_open.assert_called_once_with(Path("/tmp/pipe_ready"), os.O_RDONLY | os.O_NONBLOCK)
    mock_open.assert_called_once_with(3)
    mock_unlink.assert_called_once_with()


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
