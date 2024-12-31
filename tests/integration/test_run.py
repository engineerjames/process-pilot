from pathlib import Path  # noqa: INP001
from time import sleep

from process_pilot.pilot import ProcessPilot
from process_pilot.process import ProcessManifest


def test_integration() -> None:
    # Load the process manifest from a JSON file
    manifest_path = Path(__file__).parent / "example.json"
    manifest = ProcessManifest.from_json(manifest_path)

    # Create a ProcessPilot instance with the loaded manifest
    pilot = ProcessPilot(manifest)

    pilot.start()

    sleep(10.0)

    pilot.stop()
