import time  # noqa: INP001
from pathlib import Path


def start_pipe_service(pipe_path: Path) -> None:
    while not pipe_path.exists():
        time.sleep(1.0)

    with Path.open(pipe_path, "w") as fifo:
        print(f"Named pipe service writing to {pipe_path}")  # noqa: T201
        time.sleep(2)  # Simulate some startup time
        fifo.write("ready\n")
        fifo.flush()
        fifo.close()
        while True:
            time.sleep(1)


if __name__ == "__main__":
    start_pipe_service(Path("/tmp/pipe_service_ready"))
