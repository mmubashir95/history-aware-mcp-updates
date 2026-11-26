from pathlib import Path

import pytest

from pipelines.prepare_histor import ensure_output_outside_raw, load_config


def test_load_histor_config() -> None:
    config = load_config(Path("configs/data/histor.yaml"))
    assert config["dataset"]["name"] == "histor"


def test_load_config_requires_dataset(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("x: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset"):
        load_config(path)


def test_load_config_rejects_null_dataset(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("dataset: null\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset must be a mapping"):
        load_config(path)


def test_generated_paths_cannot_resolve_into_raw(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(raw, target_is_directory=True)
    with pytest.raises(ValueError, match="inside raw data"):
        ensure_output_outside_raw(raw, alias / "output.parquet")
    ensure_output_outside_raw(raw, tmp_path / "interim" / "output.parquet")
