import json  # noqa: INP001
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pytest_mock import MockerFixture

from process_pilot.graph import create_dependency_graph, load_manifest, main
from process_pilot.process import Process, ProcessManifest


@pytest.fixture
def sample_manifest(mocker: MockerFixture) -> ProcessManifest:
    """Create a sample manifest for testing."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    return ProcessManifest(
        processes=[
            Process(
                name="db",
                path=Path("/usr/bin/postgres"),
                ready_strategy="tcp",
                ready_params={"port": 5432},
            ),
            Process(
                name="api",
                path=Path("/usr/bin/api"),
                ready_strategy="file",
                ready_params={"path": "/tmp/ready"},
                dependencies=["db"],
            ),
        ],
    )


@pytest.fixture
def temp_manifest(tmp_path: Path) -> Path:
    """Create a temporary manifest file."""
    manifest_data = {
        "processes": [
            {
                "name": "test",
                "path": "/test/path",
                "ready_strategy": "tcp",
                "ready_params": {
                    "port": 9876,
                },
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data))
    return manifest_path


def test_load_manifest_json(temp_manifest: Path, mocker: MockerFixture) -> None:
    """Test loading a JSON manifest."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = load_manifest(temp_manifest)
    assert len(manifest.processes) == 1
    assert manifest.processes[0].name == "test"


def test_load_manifest_yaml(tmp_path: Path, mocker: MockerFixture) -> None:
    """Test loading a YAML manifest."""
    yaml_path = tmp_path / "manifest.yaml"
    yaml_path.write_text("""
    processes:
      - name: test
        path: /test/path
        ready_strategy: tcp
        ready_params:
          port: 8080
    """)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = load_manifest(yaml_path)
    assert len(manifest.processes) == 1
    assert manifest.processes[0].name == "test"


def test_load_manifest_invalid_extension(tmp_path: Path) -> None:
    """Test loading a manifest with invalid extension."""
    invalid_path = tmp_path / "manifest.txt"
    invalid_path.touch()
    with pytest.raises(ValueError, match="Manifest must be JSON or YAML file"):
        load_manifest(invalid_path)


def test_create_dependency_graph_basic(tmp_path: Path, sample_manifest: ProcessManifest) -> None:
    """Test creating a basic dependency graph."""
    output_path = create_dependency_graph(sample_manifest, "png", tmp_path)
    assert output_path.exists()
    assert output_path.suffix == ".png"


def test_create_dependency_graph_detailed(tmp_path: Path, sample_manifest: ProcessManifest) -> None:
    """Test creating a detailed dependency graph."""
    output_path = create_dependency_graph(sample_manifest, "svg", tmp_path, detailed=True)
    assert output_path.exists()
    assert output_path.suffix == ".svg"


def test_create_dependency_graph_no_ready_strategy(tmp_path: Path, mocker: MockerFixture) -> None:
    """Test creating a graph for process without ready strategy."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    manifest = ProcessManifest(
        processes=[
            Process(
                name="simple",
                path=Path("/usr/bin/simple"),
            ),
        ],
    )
    output_path = create_dependency_graph(manifest, "png", tmp_path)
    assert output_path.exists()


def test_create_dependency_graph_circular_deps(mocker: MockerFixture) -> None:
    """Test handling circular dependencies."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    with pytest.raises(ValueError, match="Circular dependency detected"):
        _ = ProcessManifest(
            processes=[
                Process(
                    name="a",
                    path=Path("/usr/bin/a"),
                    dependencies=["b"],
                ),
                Process(
                    name="b",
                    path=Path("/usr/bin/b"),
                    dependencies=["a"],
                ),
            ],
        )


def test_main_valid_args(tmp_path: Path, mocker: MockerFixture) -> None:
    """Test main function with valid arguments."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"processes": []}')

    mock_args = mocker.patch("argparse.ArgumentParser.parse_args")
    mock_args.return_value = Mock(
        manifest_path=manifest_path,
        format="png",
        output_dir=tmp_path,
        detailed=False,
    )

    main()
    assert (tmp_path / "process_dependencies.png").exists()


def test_main_invalid_manifest(tmp_path: Path, mocker: MockerFixture) -> None:
    """Test main function with invalid manifest."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("invalid json")

    mock_args = mocker.patch("argparse.ArgumentParser.parse_args")
    mock_args.return_value = Mock(
        manifest_path=manifest_path,
        format="png",
        output_dir=tmp_path,
        detailed=False,
    )

    with pytest.raises(SystemExit):
        main()


def test_main_detailed_warning(tmp_path: Path, mocker: MockerFixture) -> None:
    """Test warning when using detailed mode with non-SVG format."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"processes": []}')

    mock_args = mocker.patch("argparse.ArgumentParser.parse_args")
    mock_args.return_value = Mock(
        manifest_path=manifest_path,
        format="png",
        output_dir=tmp_path,
        detailed=True,
    )

    with patch("logging.warning") as mock_warning:
        main()
        mock_warning.assert_called_with("Detailed tooltips are only supported for SVG output")


def test_create_dependency_graph_output_dir_creation(tmp_path: Path, sample_manifest: ProcessManifest) -> None:
    """Test output directory creation."""
    output_dir = tmp_path / "nested" / "dir"
    output_path = create_dependency_graph(sample_manifest, "png", output_dir)
    assert output_path.exists()
    assert output_path.parent == output_dir


def test_create_dependency_graph_all_formats(tmp_path: Path, sample_manifest: ProcessManifest) -> None:
    """Test creating graphs in all supported formats."""
    for f in ["png", "svg", "pdf"]:
        output_path = create_dependency_graph(sample_manifest, f, tmp_path)  # type: ignore[arg-type]
        assert output_path.exists()
        assert output_path.suffix == f".{f}"


def test_graphviz_error_handling(tmp_path: Path, sample_manifest: ProcessManifest, mocker: MockerFixture) -> None:
    """Test handling Graphviz errors."""
    mocker.patch("graphviz.Digraph.render", side_effect=Exception("Graphviz error"))
    with pytest.raises(Exception, match="Graphviz error"):
        create_dependency_graph(sample_manifest, "png", tmp_path)
