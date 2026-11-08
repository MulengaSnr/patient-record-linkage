import pytest

from patient_linkage.config import load_config


def test_default_config_has_seed():
    assert isinstance(load_config()["seed"], int)


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_non_mapping_config_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ValueError):
        load_config(bad)
