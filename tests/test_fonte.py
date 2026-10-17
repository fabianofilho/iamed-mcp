"""Leitura do espelho: só as tabelas e colunas da lista fechada."""

from __future__ import annotations

import httpx
import respx

from iamed_mcp.config import Config
from iamed_mcp.fonte import CONSULTAS, carregar_tabelas
from tests.conftest import URL

SELECTS = {
    "articles": "id,title,summary,tags,published_at",
    "notion_content": "id,tipo,titulo,resumo,tags,modulo,escopo,url_midia,data_publicacao",
    "episodes": "id,title,description,spotify_url,published_at",
    "lessons": "id,title,description,module,created_at",
    "content_relevance": "content_id,especialidade,score",
}


def _rotas(status: dict[str, int] | None = None) -> dict[str, respx.Route]:
    status = status or {}
    return {
        tabela: respx.get(f"{URL}/rest/v1/{tabela}").mock(
            return_value=httpx.Response(status.get(tabela, 200), json=[{"id": tabela}])
        )
        for tabela in CONSULTAS
    }


def test_lista_fechada_de_tabelas_e_colunas() -> None:
    assert set(CONSULTAS) == set(SELECTS)
    for tabela, select in SELECTS.items():
        assert CONSULTAS[tabela]["select"] == select


def test_nenhuma_coluna_proibida() -> None:
    proibidas = {"content_markdown", "pdf_url", "audio_url", "video_url", "push_notified_at", "*"}
    for params in CONSULTAS.values():
        assert not proibidas & set(params["select"].split(","))


@respx.mock
async def test_pede_so_as_colunas_fechadas(config: Config) -> None:
    rotas = _rotas()
    carga = await carregar_tabelas(config)
    for tabela, select in SELECTS.items():
        assert rotas[tabela].calls.last.request.url.params["select"] == select
    assert (
        rotas["notion_content"].calls.last.request.url.params["tipo"]
        == "in.(news,evento,conferencias,repo)"
    )
    assert rotas["content_relevance"].calls.last.request.url.params["score"] == "gte.0.7"
    assert carga.falhas == []
    assert carga.tabelas["articles"] == [{"id": "articles"}]


@respx.mock
async def test_envia_chave_nos_cabecalhos(config: Config) -> None:
    rotas = _rotas()
    await carregar_tabelas(config)
    pedido = rotas["articles"].calls.last.request
    assert pedido.headers["apikey"] == "sb_publishable_teste"
    assert pedido.headers["authorization"] == "Bearer sb_publishable_teste"


@respx.mock
async def test_falha_parcial_nao_levanta(config: Config) -> None:
    _rotas({"episodes": 500})
    carga = await carregar_tabelas(config)
    assert carga.falhas == ["episodes"]
    assert "episodes" not in carga.tabelas
    assert carga.tabelas["lessons"] == [{"id": "lessons"}]


@respx.mock
async def test_timeout_vira_falha(config: Config) -> None:
    _rotas()
    respx.get(f"{URL}/rest/v1/lessons").mock(side_effect=httpx.ReadTimeout("lento"))
    carga = await carregar_tabelas(config)
    assert carga.falhas == ["lessons"]


@respx.mock
async def test_resposta_que_nao_e_lista_vira_falha(config: Config) -> None:
    _rotas()
    respx.get(f"{URL}/rest/v1/articles").mock(
        return_value=httpx.Response(200, json={"message": "x"})
    )
    carga = await carregar_tabelas(config)
    assert carga.falhas == ["articles"]
