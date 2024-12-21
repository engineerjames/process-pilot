import json
import subprocess
from enum import Enum
from pathlib import Path
from time import sleep

import yaml
from pydantic import BaseModel, Field


class ShutdownStrategy(str, Enum):
    RESTART = "restart"  # Restart the service in question
    DO_NOT_RESTART = "do_not_restart"  # Leave it dead
    SHUTDOWN_EVERYTHING = "shutdown_everything"  # Take down everything else with it


class ProcessHooks(str, Enum):
    ON_START = "on_start"
    ON_SHUTDOWN = "on_shutdown"
    ON_RESTART = "on_restart"


class Process(BaseModel):
    path: Path
    args: list[str] = Field(default=[])
    timeout: float | None = None
    shutdown_strategy: ShutdownStrategy | None = ShutdownStrategy.RESTART
    dependencies: list["Process"] = Field(default=[])


class ProcessManifest(BaseModel):
    processes: list[Process]

    @classmethod
    def from_json(cls, path: Path) -> "ProcessManifest":
        with Path.open(path, "r") as f:
            json_data = json.loads(f.read())

        return cls(**json_data)

    @classmethod
    def from_yaml(cls, path: Path) -> "ProcessManifest":
        with Path.open(path, "r") as f:
            yaml_data = yaml.safe_load(f)

        return cls(**yaml_data)


class ProcessPilot:
    def __init__(self, manifest: ProcessManifest, poll_interval: float = 0.1) -> None:
        self.manifest = manifest
        self.poll_interval = poll_interval
        self._processes: list[tuple[Process, subprocess.Popen[str]]] = []
        self._shutting_down: bool = False

    def start(self) -> None:
        """ """
        try:
            for entry in self.manifest.processes:
                command = [str(entry.path), *entry.args]
                new_popen_result = subprocess.Popen(command, encoding="utf-8")
                self._processes.append((entry, new_popen_result))

            while not self._shutting_down:
                for process_entry, process in self._processes:
                    result = process.poll()
                    if result is None:
                        continue

                    # exited
                    # log exited process
                    # need to remove exited process
                    match process_entry.shutdown_strategy:
                        case ShutdownStrategy.SHUTDOWN_EVERYTHING:
                            self.stop()
                        case ShutdownStrategy.DO_NOT_RESTART:
                            pass
                        case ShutdownStrategy.RESTART:
                            self._processes.append(
                                (
                                    process_entry,
                                    subprocess.Popen([str(process_entry.path), *process_entry.args], encoding="utf-8"),
                                )
                            )
                        case _:
                            pass

                sleep(self.poll_interval)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._shutting_down = True

        for process_entry, process in self._processes:
            process.terminate()

            try:
                process.wait(process_entry.timeout)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "tests" / "examples" / "services.json")
    pilot = ProcessPilot(manifest)

    pilot.start()
