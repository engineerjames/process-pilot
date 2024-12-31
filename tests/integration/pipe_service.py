import os
import select
import signal
import sys
import time
from pathlib import Path


def cleanup(pipe_path: Path) -> None:
    if pipe_path.exists():
        pipe_path.unlink()
    sys.exit(0)


def start_pipe_service(pipe_path: Path) -> None:
    if pipe_path.exists():
        pipe_path.unlink()

    os.mkfifo(pipe_path, 0o666)

    signal.signal(signal.SIGINT, lambda s, f: cleanup(pipe_path))
    signal.signal(signal.SIGTERM, lambda s, f: cleanup(pipe_path))

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
        cleanup(pipe_path)


if __name__ == "__main__":
    pipe_path = Path("/tmp/pipe_service_ready")
    start_pipe_service(pipe_path)
