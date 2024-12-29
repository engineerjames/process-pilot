import os  # noqa: INP001
import time
from pathlib import Path


def start_pipe_service(pipe_path: str) -> None:
    if not Path(pipe_path).exists():
        os.mkfifo(pipe_path)

    with Path.open(Path(pipe_path), "w") as fifo:
        print(f"Named pipe service writing to {pipe_path}")  # noqa: T201
        time.sleep(2)  # Simulate some startup time
        fifo.write("ready")
        fifo.flush()
        while True:
            time.sleep(1)


if __name__ == "__main__":
    start_pipe_service("/tmp/pipe_service_ready")  # noqa: S108
