"""Load project configuration from YAML so parameters are not hard-coded."""

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    """Read a YAML config file.

    Args:
        path: Path to the YAML file. Defaults to ``configs/default.yaml``.

    Returns:
        The parsed configuration as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file does not contain a YAML mapping.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a YAML mapping, got {type(config).__name__}")
    return config
