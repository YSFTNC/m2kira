import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json(name: str):
    return json.loads(load_text(name))


@pytest.fixture
def cfg(tmp_path):
    """Her test taze bir Config alır (testler neighborhoods listesini değiştiriyor)."""
    from m2kira.config import load_config
    c = load_config(ROOT / "config.yaml")
    c.raw["data_dir"] = str(tmp_path / "data")
    return c
