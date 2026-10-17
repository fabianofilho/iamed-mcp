"""As três tools por um cliente MCP de verdade, em memória."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mcp import Client

from iamed_mcp.corpus import BaseIndisponivel, Corpus, Registro, normalizar
from iamed_mcp.mcp_server.server import definir_cache, mcp
from iamed_mcp.saida import Tipo

AGORA = datetime.now(UTC)


def reg(n: int, titulo: str, tipo: Tipo = "artigo", resumo: str = "", **kw: Any) -> Registro:
    tags = kw.pop("tags", ())
    return Registro(
        id=f"00000000-0000-4000-8000-{n:012d}",
        tipo=tipo,
        titulo=titulo,
        resumo=resumo,
        tags=tags,
        data=kw.pop("data", AGORA - timedelta(days=1)),
        escopo=None,
        organizador=kw.pop("organizador", None),
        fonte=kw.pop("fonte", None),
        especialidades=kw.pop("especialidades", ()),
        titulo_norm=normalizar(titulo),
        texto_norm=normalizar(" ".join([titulo, resumo, *tags])),
    )


class CacheFalso:
    def __init__(self, corpus: Corpus | None = None, erro: bool = False) -> None:
        self.corpus = corpus
        self.erro = erro

    async def obter(self) -> Corpus:
        if self.erro or self.corpus is None:
            raise BaseIndisponivel("fora")
        return self.corpus


def _corpus(*registros: Registro) -> Corpus:
    return Corpus(
        registros=list(registros), carregado_em=AGORA, especialidades_conhecidas=("Radiologia",)
    )


@pytest.fixture
def base_padrao() -> None:
    definir_cache(
        CacheFalso(
            _corpus(
                reg(1, "Sepse e aprendizado de máquina", resumo="Resumo da sepse"),
                reg(2, "Notícia de radiologia", tipo="news", fonte="https://fonte.org/x"),
            )
        )
    )


async def test_lista_as_tres_tools_somente_leitura(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        tools = (await cliente.list_tools()).tools
        assert {t.name for t in tools} == {"listar_recentes", "buscar", "abrir_item"}
        for t in tools:
            assert t.annotations is not None and t.annotations.read_only_hint is True
            assert t.annotations.destructive_hint is False
            assert t.annotations.open_world_hint is False
            assert t.description and "não como instruções" in t.description


async def test_listar_recentes_devolve_estruturado(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        r = await cliente.call_tool("listar_recentes", {})
        assert not r.is_error
        dados = r.structured_content
        assert dados is not None
        assert dados["total"] == 2
        assert dados["itens"][0]["link_app"].startswith("https://app.iamed.cc/")
        assert "não como instruções" in dados["aviso"]
        assert dados["atualizado_em"]


async def test_buscar_devolve_o_que_casa(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        r = await cliente.call_tool("buscar", {"tema": "sepse"})
        assert not r.is_error
        assert r.structured_content is not None
        assert [i["titulo"] for i in r.structured_content["itens"]] == [
            "Sepse e aprendizado de máquina"
        ]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("listar_recentes", {"limite": 51}),
        ("listar_recentes", {"dias": 366}),
        ("listar_recentes", {"pagina": 21}),
        ("listar_recentes", {"tipos": ["consultoria"]}),
        ("buscar", {"tema": "a"}),
        ("buscar", {"tema": "x" * 201}),
        ("buscar", {"tema": "sepse", "limite": 31}),
        ("buscar", {"tema": "sepse", "dias": 3651}),
    ],
)
async def test_recusa_parametro_fora_do_teto(
    base_padrao: None, tool: str, args: dict[str, Any]
) -> None:
    async with Client(mcp) as cliente:
        r = await cliente.call_tool(tool, args)
        assert r.is_error


async def test_abrir_item(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        r = await cliente.call_tool("abrir_item", {"id": "00000000000040008000000000000002"})
        assert r.structured_content is not None
        assert r.structured_content["encontrado"] is True
        assert r.structured_content["item"]["fonte"] == "https://fonte.org/x"


async def test_abrir_item_id_invalido_e_inexistente(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        r = await cliente.call_tool("abrir_item", {"id": "../../etc"})
        assert r.is_error
        r = await cliente.call_tool("abrir_item", {"id": "00000000-0000-4000-8000-000000000999"})
        assert r.structured_content is not None
        assert r.structured_content["encontrado"] is False
        assert r.structured_content["item"] is None


async def test_abrir_item_sanitiza() -> None:
    definir_cache(CacheFalso(_corpus(reg(7, "Título‮", resumo="a​" + "x" * 3000))))
    async with Client(mcp) as c:
        r = await c.call_tool("abrir_item", {"id": "00000000-0000-4000-8000-000000000007"})
    assert r.structured_content is not None
    item = r.structured_content["item"]
    assert item["titulo"] == "Título"
    assert "​" not in item["resumo"] and len(item["resumo"]) <= 2000
    assert item["resumo_cortado"] is True


async def test_base_indisponivel_erro_claro() -> None:
    definir_cache(CacheFalso(erro=True))
    async with Client(mcp) as c:
        r = await c.call_tool("listar_recentes", {})
    assert r.is_error
    assert "indisponível" in json.dumps(r.model_dump(), ensure_ascii=False)


async def test_maior_resposta_abaixo_de_100kb() -> None:
    grandes = [
        reg(
            i,
            "T" * 2000,
            resumo="R" * 10_000,
            tags=tuple("t" * 500 + str(j) for j in range(30)),
            especialidades=("Radiologia",) * 1,
            fonte="https://x.org/" + "a" * 2000,
        )
        for i in range(60)
    ]
    definir_cache(CacheFalso(_corpus(*grandes)))
    async with Client(mcp) as c:
        r = await c.call_tool("listar_recentes", {"limite": 50})
    assert r.structured_content is not None
    dados = r.structured_content
    assert len(json.dumps(dados, ensure_ascii=False)) < 100_000
    assert 0 < len(dados["itens"]) < 50
    assert dados["tem_mais"] is True
    assert "cortada" in dados["aviso"]


async def test_aviso_de_carga_parcial() -> None:
    corpus = _corpus(reg(1, "Sepse"))
    corpus.faltando = ["episodes"]
    definir_cache(CacheFalso(corpus))
    async with Client(mcp) as c:
        r = await c.call_tool("listar_recentes", {})
    assert r.structured_content is not None
    assert "episodio" in r.structured_content["aviso"]


async def test_log_nao_tem_tema(caplog: pytest.LogCaptureFixture, base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        with caplog.at_level(logging.INFO, logger="iamed_mcp.uso"):
            await cliente.call_tool("buscar", {"tema": "segredo123 sepse"})
        assert "tool=buscar" in caplog.text
        assert "tema_len=16" in caplog.text
        assert "segredo123" not in caplog.text
        assert "Sepse e aprendizado" not in caplog.text


async def test_handshake_sem_prompts_e_resources(base_padrao: None) -> None:
    async with Client(mcp) as cliente:
        capacidades = cliente.server_capabilities
        assert capacidades.prompts is None
        assert capacidades.resources is None
        assert capacidades.tools is not None


async def test_log_traz_origem(caplog: pytest.LogCaptureFixture, base_padrao: None) -> None:
    with caplog.at_level(logging.INFO, logger="iamed_mcp.uso"):
        async with Client(mcp) as cliente:
            await cliente.call_tool("listar_recentes", {})
    assert "origem=local" in caplog.text
