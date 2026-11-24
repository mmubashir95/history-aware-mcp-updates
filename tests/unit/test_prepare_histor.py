from pathlib import Path

import pytest

from pipelines.prepare_histor import load_config


def test_load_histor_config() -> None:
    config = load_config(Path("configs/data/histor.yaml"))
    assert config["dataset"]["name"] == "histor"


def test_load_config_requires_dataset(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("x: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset"):
        load_config(path)
