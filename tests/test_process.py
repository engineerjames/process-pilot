from pathlib import Path

from process_pilot.process import ProcessManifest


def test_can_load_json() -> None:
    manifest = ProcessManifest.from_json(Path(__file__).parent / "examples" / "services.json")

    assert len(manifest.processes) == 1
    assert manifest.processes[0].args == ["5"]
    assert manifest.processes[0].path == Path("sleep")
    assert manifest.processes[0].timeout == 3.0  # noqa: PLR2004


def test_can_load_yaml() -> None:
    manifest = ProcessManifest.from_yaml(Path(__file__).parent / "examples" / "services.yaml")

    assert len(manifest.processes) == 1
    assert manifest.processes[0].args == ["5"]
    assert manifest.processes[0].path == Path("sleep")
    assert manifest.processes[0].timeout == 1.0
