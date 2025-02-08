import os  # noqa: INP001
from pathlib import Path
from time import sleep

import pytest

from process_pilot.pilot import ProcessPilot
from process_pilot.process import ProcessManifest


@pytest.mark.skipif("GITLAB_CI" in os.environ, reason="Skipping test that actually does process modification")
def test_integration() -> None:
    # Load the process manifest from a JSON file
    manifest_path = Path(__file__).parent / "example.json"
    manifest = ProcessManifest.from_json(manifest_path)

    # Create a ProcessPilot instance with the loaded manifest
    pilot = ProcessPilot(manifest)

    pilot.start()

    sleep(15.0)

    pilot.stop()


if __name__ == "__main__":
    # Load the process manifest from a JSON file
    manifest_path = Path(__file__).parent / "example.json"
    manifest = ProcessManifest.from_json(manifest_path)

    # Create a ProcessPilot instance with the loaded manifest
    pilot = ProcessPilot(manifest)

    pilot.start()
