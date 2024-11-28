import json
import subprocess
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel


class ProcessStrategy(str, Enum):
    RESTART = "restart"  # Restart the service in question
    DO_NOT_RESTART = "do_not_restart"  # Leave it dead
    SHUTDOWN_EVERYTHING = "shutdown_everything"  # Take down everything else with it


class ProcessHooks(str, Enum):
    ON_START = "on_start"
    ON_SHUTDOWN = "on_shutdown"
    ON_RESTART = "on_restart"


class Process(BaseModel):
    path: Path
    args: list[str] | None = None
    timeout: float | None = None


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
    def __init__(self, manifest: ProcessManifest) -> None:
        self.manifest = manifest

        self.running_processes: list[subprocess.Popen[str]] = []

    def start(self) -> None:
        for entry in self.manifest.processes:
            command = [str(entry.path)] if not entry.args else [str(entry.path), *entry.args]

            x = subprocess.Popen(command, encoding="utf-8")

            self.running_processes.append(x)

        print("x")

        while True:
            y = self.running_processes[0].poll()
            if y is not None:
                print("DONE")
                print(y)
                print(self.running_processes[0].communicate())
                break


if __name__ == "__main__":
    manifest = ProcessManifest.from_json(Path(__file__).parent.parent / "tests" / "examples" / "services.json")
    pilot = ProcessPilot(manifest)

    pilot.start()
