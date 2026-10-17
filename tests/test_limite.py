"""Limitador, origem, proteção de Host e o 429 do modo connector."""

from __future__ import annotations

from typing import Any

import pytest

from iamed_mcp.config import Config
from iamed_mcp.mcp_server.limite import (
    LimitadorPorOrigem,
    origem_da_requisicao,
    zerar_ultimo_octeto,
)
from iamed_mcp.mcp_server.server import _com_limite, _seguranca_de_transporte


def test_teto_por_origem() -> None:
    limitador = LimitadorPorOrigem(limite_por_minuto=2, limite_global_por_minuto=100)
    assert limitador.permitir("a") and limitador.permitir("a")
    assert not limitador.permitir("a")
    assert limitador.motivo_ultima_recusa == "origem"
    assert limitador.permitir("b")


def test_teto_global_protege_independente_da_origem() -> None:
    limitador = LimitadorPorOrigem(limite_por_minuto=100, limite_global_por_minuto=3)
    assert all(limitador.permitir(f"10.0.0.{i}") for i in range(3))
    assert not limitador.permitir("10.0.0.99")
    assert limitador.motivo_ultima_recusa == "global"


def test_origem_usa_forwarded_for_quando_ha_proxy() -> None:
    scope: dict[str, Any] = {
        "headers": [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.9")],
        "client": ("127.0.0.1", 5000),
    }
    assert origem_da_requisicao(scope) == "203.0.113.9"


def test_origem_ignora_forwarded_for_de_quem_nao_e_proxy() -> None:
    scope: dict[str, Any] = {
        "headers": [(b"x-forwarded-for", b"203.0.113.9")],
        "client": ("198.51.100.7", 5000),
    }
    assert origem_da_requisicao(scope) == "198.51.100.7"


def test_tabela_cheia_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    from iamed_mcp.mcp_server import limite

    monkeypatch.setattr(limite, "MAX_ORIGENS", 2)
    limitador = LimitadorPorOrigem(limite_por_minuto=100)
    assert limitador.permitir("a") and limitador.permitir("b")
    assert not limitador.permitir("c")
    assert limitador.motivo_ultima_recusa == "tabela"


def test_zerar_ultimo_octeto() -> None:
    assert zerar_ultimo_octeto("200.1.2.3") == "200.1.2.0"
    assert zerar_ultimo_octeto("2001:db8:85a3:8d3:1319:8a2e:370:7348") == "2001:db8:85a3::"
    assert zerar_ultimo_octeto("desconhecido") == "desconhecido"


async def test_middleware_429() -> None:
    chamadas = 0

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal chamadas
        chamadas += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    protegido = _com_limite(app, limite_por_minuto=60, limite_global=300)
    status: list[int] = []
    cabecalhos: list[Any] = []

    async def send(mensagem: dict[str, Any]) -> None:
        if mensagem["type"] == "http.response.start":
            status.append(mensagem["status"])
            cabecalhos.append(dict(mensagem["headers"]))

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    scope = {"type": "http", "client": ("198.51.100.7", 1), "headers": []}
    for _ in range(61):
        await protegido(scope, receive, send)
    assert status[:60] == [200] * 60
    assert status[60] == 429
    assert cabecalhos[60][b"retry-after"] == b"60"
    assert chamadas == 60


def _config(**kw: Any) -> Config:
    return Config(_env_file=None, **kw)  # type: ignore[call-arg]


def test_sem_host_publico_mantem_o_padrao_do_sdk() -> None:
    assert _seguranca_de_transporte(_config(http_hosts_publicos=[])) is None


def test_host_publico_entra_sem_derrubar_o_loopback() -> None:
    regras = _seguranca_de_transporte(_config(http_hosts_publicos=["debian-f.tailf42a96.ts.net"]))
    assert regras is not None
    assert regras.enable_dns_rebinding_protection is True
    assert "debian-f.tailf42a96.ts.net" in regras.allowed_hosts
    assert "127.0.0.1:*" in regras.allowed_hosts


def test_host_de_fora_da_lista_continua_recusado() -> None:
    from mcp.server.transport_security import TransportSecurityMiddleware

    guarda = TransportSecurityMiddleware(
        _seguranca_de_transporte(_config(http_hosts_publicos=["debian-f.tailf42a96.ts.net"]))
    )
    assert guarda._validate_host("debian-f.tailf42a96.ts.net") is True
    assert guarda._validate_host("site-do-atacante.exemplo") is False
    assert guarda._validate_host(None) is False
