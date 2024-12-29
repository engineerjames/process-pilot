import threading  # noqa: INP001
from pathlib import Path
from time import sleep

from process_pilot.process import ProcessManifest, ProcessPilot


def test_integration() -> None:
    # Load the process manifest from a JSON file
    manifest_path = Path(__file__).parent / "example.json"
    manifest = ProcessManifest.from_json(manifest_path)

    # Create a ProcessPilot instance with the loaded manifest
    pilot = ProcessPilot(manifest)

    def start_processes() -> None:
        pilot.start()

    # Start the manage_processes function in a separate thread
    thread = threading.Thread(target=start_processes)
    thread.start()

    sleep(10.0)
    pilot.stop()
    thread.join(5.0)
    assert not thread.is_alive()
