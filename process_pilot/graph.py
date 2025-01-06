import argparse  # noqa: D100
import logging
import sys
from pathlib import Path
from typing import Literal

import graphviz

from process_pilot.process import ProcessManifest


def create_dependency_graph(
    manifest: ProcessManifest,
    output_format: Literal["png", "svg", "pdf"] = "png",
    output_dir: Path | None = None,
    *,
    detailed: bool = False,
) -> Path:
    """
    Create a dependency graph from a process manifest.

    :param manifest: The process manifest to generate the graph from.
    :param output_format: The output format for the graph (png, svg, pdf).
    :param output_dir: The directory to save the generated graph.
    :param detailed: Include detailed process information in tooltips.

    :returns: The path to the generated graph file.
    """
    dot = graphviz.Digraph(comment="Process Dependencies")
    dot.attr(rankdir="LR")

    # Color mapping for ready strategies
    colors = {"tcp": "lightblue", "file": "lightgreen", "pipe": "lightyellow"}

    # Add all processes as nodes
    for process in manifest.processes:
        # Node attributes
        if process.ready_strategy:
            attrs = {"style": "filled", "fillcolor": colors.get(process.ready_strategy, "white")}
        else:
            attrs = {"style": "filled"}

        if detailed:
            attrs["tooltip"] = (
                f"Path: {process.path}\n"
                f"Ready Strategy: {process.ready_strategy}\n"
                f"Timeout: {process.ready_timeout_sec}s"
            )

        dot.node(process.name, process.name, **attrs)

        # Add dependency edges
        if process.dependencies:
            for dep in process.dependencies:
                dep_name = dep if isinstance(dep, str) else dep.name
                dot.edge(dep_name, process.name)

    # Determine output path
    output_path = Path(output_dir or ".") / f"process_dependencies.{output_format}"

    # Render and save
    rendered_file_location = dot.render(
        filename=output_path.stem,
        directory=output_path.parent,
        format=output_format,
        cleanup=True,
    )

    return Path(rendered_file_location).absolute()


def load_manifest(manifest_path: Path) -> ProcessManifest:
    """
    Load a process manifest from a JSON or YAML file.

    :param manifest_path: Path to the manifest file.

    :returns: The loaded process manifest.

    :raises FileNotFoundError: If the manifest file does not exist.
    :raises ValueError: If the manifest file is not JSON or YAML.
    """
    # Validate manifest path
    if not manifest_path.exists():
        msg = f"Manifest file not found: {manifest_path}"
        raise FileNotFoundError(msg)

    # Load manifest based on file extension
    if manifest_path.suffix == ".json":
        manifest = ProcessManifest.from_json(manifest_path)
    elif manifest_path.suffix in {".yml", ".yaml"}:
        manifest = ProcessManifest.from_yaml(manifest_path)
    else:
        msg = "Manifest must be JSON or YAML file"
        raise ValueError(msg)

    return manifest


def main() -> None:
    """CLI entry point for dependency graph generation."""
    parser = argparse.ArgumentParser(description="Generate a dependency graph from a process manifest file")

    parser.add_argument("manifest_path", type=Path, help="Path to the manifest file (JSON or YAML)")

    parser.add_argument("--format", choices=["png", "svg", "pdf"], default="png", help="Output format for the graph")

    parser.add_argument("--output-dir", type=Path, help="Directory to save the generated graph")

    parser.add_argument("--detailed", action="store_true", help="Include detailed process information in tooltips")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    if args.detailed and args.format != "svg":
        logging.warning("Detailed tooltips are only supported for SVG output")

    try:
        # Load manifest
        manifest = load_manifest(args.manifest_path)

        # Create output directory if needed
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate graph
        output_path = create_dependency_graph(
            manifest,
            args.format,
            args.output_dir,
            detailed=args.detailed,
        )

        logging.debug("Generated dependency graph: %s", output_path)

    except Exception:
        logging.exception("Error generating graph")
        sys.exit(1)


if __name__ == "__main__":
    main()
