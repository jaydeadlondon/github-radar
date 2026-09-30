import tomllib
from pathlib import Path


def test_top_level_src_modules_are_declared_for_setuptools() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    declared = set(pyproject["tool"]["setuptools"]["py-modules"])
    actual = {path.stem for path in (root / "src").glob("*.py")}
    assert declared == actual
