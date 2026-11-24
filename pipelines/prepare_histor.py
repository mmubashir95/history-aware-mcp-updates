#!/usr/bin/env python3
"""Validate and run the HISTOR preparation workflow.

Stages are deliberately introduced one at a time as audit scripts are migrated
into the package; this entry point prevents the workflow contract from drifting.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    """Load and minimally validate a HISTOR pipeline configuration."""
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or "dataset" not in config:
        raise ValueError("Configuration must contain a dataset mapping.")
    for key in ("name", "raw_path", "output_path"):
        if key not in config["dataset"]:
            raise ValueError(f"dataset.{key} is required.")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    dataset = config["dataset"]
    print(f"Validated {dataset['name']} configuration: {args.config}")
    print("Preparation stages will run here as they are implemented.")


if __name__ == "__main__":
    main()
