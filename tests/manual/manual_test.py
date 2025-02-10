from pathlib import Path  # noqa: INP001
from time import sleep

from process_pilot.pilot import ProcessPilot
from process_pilot.process import ProcessManifest

if __name__ == "__main__":
    try:
        process_manifest = ProcessManifest.from_yaml(Path(__file__).parent / "services.yaml")
        pilot = ProcessPilot(process_manifest)

        pilot.start()

        while pilot.is_running():
            sleep(1.0)

        print("Process pilot stopped.")  # noqa: T201
    except KeyboardInterrupt:
        pilot.stop()
        print("Caught KeyboardInterrupt")  # noqa: T201
