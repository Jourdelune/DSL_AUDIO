"""Shared pytest fixtures and session-level setup."""
from __future__ import annotations

from pathlib import Path

import pytest

TEST_AUDIO = Path(__file__).parent.parent / "test.mp3"
MIX_DIR = Path(__file__).parent / "mix_files"
RENDERED_DIR = Path(__file__).parent / "rendered"


@pytest.fixture(scope="session", autouse=True)
def ensure_dirs():
    MIX_DIR.mkdir(exist_ok=True)
    RENDERED_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def audio_path() -> Path:
    return TEST_AUDIO


@pytest.fixture(scope="session")
def mix_dir() -> Path:
    return MIX_DIR


@pytest.fixture(scope="session")
def rendered_dir() -> Path:
    return RENDERED_DIR
