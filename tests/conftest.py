"""Fixtures compartilhadas."""

from __future__ import annotations

import pytest

from iamed_mcp.config import Config

URL = "https://teste.supabase.co"


@pytest.fixture
def config() -> Config:
    return Config(
        _env_file=None,  # type: ignore[call-arg]
        supabase_url=URL,
        supabase_anon_key="sb_publishable_teste",  # type: ignore[arg-type]
    )
