import time  # noqa: INP001
from pathlib import Path


def start_file_service(file_path: str) -> None:
    ready_file = Path(file_path)
    print(f"File service creating {file_path}")  # noqa: T201
    time.sleep(2)  # Simulate some startup time
    ready_file.touch()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    start_file_service("/tmp/file_service_ready.txt")
