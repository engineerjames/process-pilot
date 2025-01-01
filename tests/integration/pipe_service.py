import os  # noqa: INP001
import select
import signal
import sys
import time
from pathlib import Path

# ruff: noqa: F401, RUF100, T201, BLE001

if sys.platform == "win32":
    import pywintypes
    import win32event
    import win32file
    import win32pipe

    def cleanup_windows(pipe_handle) -> None:  # noqa: ANN001
        if pipe_handle:
            win32file.CloseHandle(pipe_handle)
        sys.exit(0)

    def start_pipe_service_windows(pipe_name: str) -> None:
        pipe_path = f"\\\\.\\pipe\\{pipe_name}"

        try:
            print(f"Named pipe service creating pipe at {pipe_path}")

            pipe_handle = win32pipe.CreateNamedPipe(
                pipe_path,
                win32pipe.PIPE_ACCESS_OUTBOUND,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1,
                65536,
                65536,
                0,
                None,
            )

            # Set up cleanup on Ctrl+C
            def handle_signal(_: int, _frame: object) -> None:
                cleanup_windows(pipe_handle)

            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)

            while True:
                try:
                    win32pipe.ConnectNamedPipe(pipe_handle, None)
                    win32file.WriteFile(pipe_handle, b"ready\n")
                    print("Successfully wrote ready signal")

                    while True:
                        time.sleep(1)

                except pywintypes.error as e:
                    print(f"Windows pipe error: {e}")
                    time.sleep(0.1)

        except Exception as e:
            print(f"Error in pipe service: {e}")
        finally:
            cleanup_windows(pipe_handle)
else:

    def cleanup_unix(pipe_path: Path) -> None:
        if pipe_path.exists():
            pipe_path.unlink()
        sys.exit(0)

    def start_pipe_service(pipe_path: Path) -> None:
        if pipe_path.exists():
            pipe_path.unlink()

        os.mkfifo(pipe_path, 0o666)

        signal.signal(signal.SIGINT, lambda s, f: cleanup_unix(pipe_path))  # noqa: ARG005
        signal.signal(signal.SIGTERM, lambda s, f: cleanup_unix(pipe_path))  # noqa: ARG005

        try:
            print(f"Named pipe service creating pipe at {pipe_path}")

            while True:
                try:
                    # Open pipe in non-blocking mode
                    fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)

                    # Create polling object for write operations
                    poller = select.poll()
                    poller.register(fd, select.POLLOUT)

                    # Wait for pipe to be ready for writing
                    events = poller.poll(1000)  # 1 second timeout

                    for _, event in events:
                        if event & select.POLLOUT:
                            os.write(fd, b"ready\n")

                            # Keep pipe open
                            while True:
                                time.sleep(1)

                except OSError as e:
                    print(f"Waiting for reader: {e}")
                    time.sleep(0.1)
                    continue

        except Exception as e:
            print(f"Error in pipe service: {e}")
        finally:
            if "fd" in locals():
                os.close(fd)
            cleanup_unix(pipe_path)


if __name__ == "__main__":
    if sys.platform == "win32":
        start_pipe_service_windows("pipe_service_ready")
    else:
        pipe_path = Path("/tmp/pipe_service_ready")
        start_pipe_service(pipe_path)
