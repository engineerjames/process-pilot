from pathlib import Path  # noqa: INP001

from process_pilot.process import ProcessManifest, ProcessPilot

# Load the process manifest from a JSON file
manifest_path = Path("path/to/your/manifest.json")
manifest = ProcessManifest.from_json(manifest_path)

# Create a ProcessPilot instance with the loaded manifest
pilot = ProcessPilot(manifest)

# Start managing the processes
pilot.start()
