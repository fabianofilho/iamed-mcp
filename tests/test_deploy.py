"""A unit do systemd sobe o conector de verdade."""

from __future__ import annotations

from pathlib import Path

UNIT = (Path(__file__).parent.parent / "deploy" / "iamed-connector.service").read_text()


def _linhas(chave: str) -> list[str]:
    return [linha.split("=", 1)[1] for linha in UNIT.splitlines() if linha.startswith(f"{chave}=")]


def test_env_file_nao_sobrescreve_o_modo_conector() -> None:
    # EnvironmentFile vence Environment no systemd: um .env feito do .env.example
    # (TRANSPORTE=stdio, HTTP_HOSTS_PUBLICOS vazio) derrubaria o conector. O
    # pydantic-settings já lê o .env do WorkingDirectory, abaixo do ambiente.
    assert _linhas("EnvironmentFile") == []
    ambiente = _linhas("Environment")
    assert "TRANSPORTE=streamable-http" in ambiente
    assert "HTTP_HOSTS_PUBLICOS=debian-f.tailf42a96.ts.net,mcp.iamed.cc" in ambiente
    assert "HTTP_PORTA=8107" in ambiente


def test_roda_o_binario_do_venv_sem_uv() -> None:
    # Com ProtectHome=read-only o uv não pode gravar cache nem sincronizar.
    assert _linhas("ExecStart") == ["%h/iamed-mcp/.venv/bin/iamed-mcp"]


def test_limites_de_recurso() -> None:
    assert _linhas("MemoryMax")
    assert _linhas("ProtectHome") == ["read-only"]
