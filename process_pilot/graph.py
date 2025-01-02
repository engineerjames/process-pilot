import argparse
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
    detailed: bool = False,
) -> Path:
    """Create a dependency graph from a process manifest."""
    dot = graphviz.Digraph(comment="Process Dependencies")
    dot.attr(rankdir="LR")

    # Color mapping for ready strategies
    colors = {"tcp": "lightblue", "file": "lightgreen", "pipe": "lightyellow"}

    # Add all processes as nodes
    for process in manifest.processes:
        # Node attributes
        attrs = {"style": "filled", "fillcolor": colors.get(process.ready_strategy, "white")}

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
                dot.edge(dep, process.name)

    # Determine output path
    output_path = Path(output_dir or ".") / f"process_dependencies.{output_format}"

    # Render and save
    dot.render(output_path.stem, format=output_format, cleanup=True)
    return output_path


def main() -> None:
    """CLI entry point for dependency graph generation."""
    parser = argparse.ArgumentParser(description="Generate a dependency graph from a process manifest file")

    parser.add_argument("manifest_path", type=Path, help="Path to the manifest file (JSON or YAML)")

    parser.add_argument("--format", choices=["png", "svg", "pdf"], default="png", help="Output format for the graph")

    parser.add_argument("--output-dir", type=Path, help="Directory to save the generated graph")

    parser.add_argument("--detailed", action="store_true", help="Include detailed process information in tooltips")

    args = parser.parse_args()

    try:
        # Validate manifest path
        if not args.manifest_path.exists():
            msg = f"Manifest file not found: {args.manifest_path}"
            raise FileNotFoundError(msg)

        # Load manifest based on file extension
        if args.manifest_path.suffix == ".json":
            manifest = ProcessManifest.from_json(args.manifest_path)
        elif args.manifest_path.suffix in {".yml", ".yaml"}:
            manifest = ProcessManifest.from_yaml(args.manifest_path)
        else:
            msg = "Manifest must be JSON or YAML file"
            raise ValueError(msg)

        # Create output directory if needed
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate graph
        output_path = create_dependency_graph(manifest, args.format, args.output_dir, args.detailed)
        print(f"Generated dependency graph: {output_path}")

    except Exception as e:
        logging.error("Error generating graph: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
