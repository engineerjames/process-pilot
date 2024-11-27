import json
from pathlib import Path

import yaml
from pydantic import BaseModel


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
