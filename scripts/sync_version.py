#!/usr/bin/env python3
"""
Sync version from the single source (apex_brain/brain/version.py) into
apex_brain/config.yaml and pyproject.toml. Run from repo root after bumping
__version__ in brain/version.py.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APEX_BRAIN = REPO_ROOT / "apex_brain"


def get_version() -> str:
    sys.path.insert(0, str(APEX_BRAIN))
    try:
        from brain.version import __version__
        return __version__
    finally:
        sys.path.pop(0)


def main() -> None:
    version = get_version()
    config_yaml = APEX_BRAIN / "config.yaml"
    pyproject = REPO_ROOT / "pyproject.toml"

    # config.yaml: version: "x.y.z"
    text = config_yaml.read_text(encoding="utf-8")
    text = re.sub(
        r'version:\s*"[^"]*"', f'version: "{version}"', text, count=1
    )
    config_yaml.write_text(text, encoding="utf-8")

    # pyproject.toml: version = "x.y.z"
    text = pyproject.read_text(encoding="utf-8")
    text = re.sub(
        r'^version\s*=\s*"[^"]*"',
        f'version = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    pyproject.write_text(text, encoding="utf-8")

    print(
        f"Synced version {version} -> apex_brain/config.yaml, pyproject.toml"
    )


if __name__ == "__main__":
    main()
