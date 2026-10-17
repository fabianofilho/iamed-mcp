"""Montagem do corpus a partir das tabelas e o cache de 5 minutos."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from iamed_mcp.config import Config
from iamed_mcp.corpus import BaseIndisponivel, CacheCorpus, montar_registros, normalizar
from iamed_mcp.fonte import CONSULTAS, Carga

AGORA = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ID_A = "34034afb-03ec-81a1-b2c3-d4e5f6a7b801"
ID_B = "34034afb-03ec-81a1-b2c3-d4e5f6a7b802"
ID_C = "34034afb-03ec-81a1-b2c3-d4e5f6a7b803"
ID_D = "34034afb-03ec-81a1-b2c3-d4e5f6a7b804"
ID_E = "34034afb-03ec-81a1-b2c3-d4e5f6a7b805"


def _iso(dias: float) -> str:
    return (AGORA - timedelta(days=dias)).isoformat()


def _carga(**tabelas: list[dict[str, Any]]) -> Carga:
    base: dict[str, list[dict[str, Any]]] = {t: [] for t in CONSULTAS}
    base.update(tabelas)
    return Carga(tabelas=base)


def test_normalizar() -> None:
    assert normalizar("  Ética   MÉDICA\n") == "etica medica"


def test_mapeia_cada_tabela() -> None:
    carga = _carga(
        articles=[
            {
                "id": ID_A,
                "title": "Artigo",
                "summary": "Res",
                "tags": ["IA"],
                "published_at": _iso(1),
            }
        ],
        notion_content=[
            {
                "id": ID_B,
                "tipo": "news",
                "titulo": "News",
                "resumo": "R",
                "tags": None,
                "modulo": None,
                "escopo": "Nacional",
                "url_midia": "https://fonte.org/n",
                "data_publicacao": _iso(2),
            },
            {
                "id": ID_C,
                "tipo": "repo",
                "titulo": "Repo",
                "resumo": "R",
                "tags": ["ML"],
                "modulo": "GitHub, Python",
                "escopo": None,
                "url_midia": "https://github.com/x/y",
                "data_publicacao": _iso(3),
            },
        ],
        episodes=[
            {
                "id": ID_D,
                "title": "Ep",
                "description": "Desc",
                "spotify_url": "https://open.spotify.com/e",
                "published_at": _iso(4),
            }
        ],
        lessons=[
            {
                "id": ID_E,
                "title": "Aula",
                "description": "D",
                "module": "Módulo 1",
                "created_at": _iso(5),
            }
        ],
    )
    regs = {r.id: r for r in montar_registros(carga, AGORA)}
    artigo, news, repo, ep, aula = regs[ID_A], regs[ID_B], regs[ID_C], regs[ID_D], regs[ID_E]
    assert (artigo.tipo, artigo.titulo, artigo.resumo, artigo.tags) == (
        "artigo",
        "Artigo",
        "Res",
        ("IA",),
    )
    assert artigo.fonte is None
    assert artigo.data == AGORA - timedelta(days=1)
    assert (news.tipo, news.escopo, news.fonte, news.tags) == (
        "news",
        "nacional",
        "https://fonte.org/n",
        (),
    )
    assert repo.tipo == "repo" and repo.tags == ("ML", "GitHub", "Python")
    assert (ep.tipo, ep.resumo, ep.fonte) == ("episodio", "Desc", "https://open.spotify.com/e")
    assert (aula.tipo, aula.organizador, aula.fonte) == ("aula", "Módulo 1", None)
    assert artigo.titulo_norm == "artigo"


def test_organizador_do_evento() -> None:
    carga = _carga(
        notion_content=[
            {
                "id": ID_A,
                "tipo": "evento",
                "titulo": "Congresso",
                "resumo": "",
                "tags": [],
                "modulo": "SBIS",
                "escopo": "Internacional",
                "url_midia": None,
                "data_publicacao": _iso(-5),
            }
        ]
    )
    (evento,) = montar_registros(carga, AGORA)
    assert evento.organizador == "SBIS"
    assert evento.escopo == "internacional"


def test_descarta_sem_titulo_e_aceita_nulos() -> None:
    carga = _carga(
        articles=[
            {"id": ID_A, "title": None, "summary": "x", "tags": None, "published_at": _iso(1)},
            {"id": ID_B, "title": "   ", "summary": "x", "tags": None, "published_at": _iso(1)},
            {"id": ID_C, "title": "Ok", "summary": None, "tags": None, "published_at": None},
        ]
    )
    (reg,) = montar_registros(carga, AGORA)
    assert reg.id == ID_C and reg.data is None and reg.tags == () and reg.resumo == ""


def test_descarta_id_invalido() -> None:
    carga = _carga(
        articles=[
            {"id": "nao-e-uuid", "title": "X", "summary": "", "tags": [], "published_at": _iso(1)}
        ]
    )
    assert montar_registros(carga, AGORA) == []


def test_dedup_por_id_com_e_sem_hifen() -> None:
    carga = _carga(
        articles=[
            {"id": ID_A, "title": "Primeiro", "summary": "", "tags": [], "published_at": _iso(1)}
        ],
        notion_content=[
            {
                "id": ID_A.replace("-", ""),
                "tipo": "news",
                "titulo": "Segundo",
                "resumo": "",
                "tags": [],
                "modulo": None,
                "escopo": None,
                "url_midia": None,
                "data_publicacao": _iso(1),
            }
        ],
    )
    (reg,) = montar_registros(carga, AGORA)
    assert reg.titulo == "Primeiro"


def test_artigo_e_episodio_do_futuro_ficam_fora() -> None:
    carga = _carga(
        articles=[
            {"id": ID_A, "title": "Futuro", "summary": "", "tags": [], "published_at": _iso(-1)}
        ],
        episodes=[
            {
                "id": ID_B,
                "title": "Futuro",
                "description": "",
                "spotify_url": None,
                "published_at": _iso(-1),
            }
        ],
        notion_content=[
            {
                "id": ID_C,
                "tipo": "evento",
                "titulo": "Evento futuro",
                "resumo": "",
                "tags": [],
                "modulo": None,
                "escopo": None,
                "url_midia": None,
                "data_publicacao": _iso(-10),
            }
        ],
    )
    assert [r.id for r in montar_registros(carga, AGORA)] == [ID_C]


def test_especialidades_do_jev() -> None:
    carga = _carga(
        articles=[{"id": ID_A, "title": "X", "summary": "", "tags": [], "published_at": _iso(1)}],
        content_relevance=[
            {"content_id": ID_A.replace("-", ""), "especialidade": "Radiologia", "score": 0.9},
            {"content_id": ID_A, "especialidade": "Cardiologia", "score": 0.7},
        ],
    )
    (reg,) = montar_registros(carga, AGORA)
    assert reg.especialidades == ("Cardiologia", "Radiologia")


def test_fonte_so_http() -> None:
    carga = _carga(
        notion_content=[
            {
                "id": ID_A,
                "tipo": "news",
                "titulo": "N",
                "resumo": "",
                "tags": [],
                "modulo": None,
                "escopo": None,
                "url_midia": "javascript:alert(1)",
                "data_publicacao": _iso(1),
            }
        ]
    )
    (reg,) = montar_registros(carga, AGORA)
    assert reg.fonte is None


def test_tipo_desconhecido_fica_fora() -> None:
    carga = _carga(
        notion_content=[
            {
                "id": ID_A,
                "tipo": "consultoria",
                "titulo": "N",
                "resumo": "",
                "tags": [],
                "modulo": None,
                "escopo": None,
                "url_midia": None,
                "data_publicacao": _iso(1),
            }
        ]
    )
    assert montar_registros(carga, AGORA) == []


# --- cache ---------------------------------------------------------------


class Relogio:
    def __init__(self) -> None:
        self.agora = AGORA

    def __call__(self) -> datetime:
        return self.agora


def _boa() -> Carga:
    return _carga(
        articles=[{"id": ID_A, "title": "X", "summary": "", "tags": [], "published_at": _iso(1)}]
    )


class Carregador:
    def __init__(self, *cargas: Carga, espera: float = 0) -> None:
        self.cargas = list(cargas)
        self.chamadas = 0
        self.espera = espera

    async def __call__(self, config: Config) -> Carga:
        self.chamadas += 1
        if self.espera:
            await asyncio.sleep(self.espera)
        return self.cargas[min(self.chamadas - 1, len(self.cargas) - 1)]


def _falha_total() -> Carga:
    return Carga(tabelas={}, falhas=list(CONSULTAS))


async def test_cache_reaproveita_por_300s(config: Config) -> None:
    relogio, carregar = Relogio(), Carregador(_boa())
    cache = CacheCorpus(config, carregar=carregar, relogio=relogio)
    await cache.obter()
    relogio.agora = AGORA + timedelta(seconds=299)
    await cache.obter()
    assert carregar.chamadas == 1
    relogio.agora = AGORA + timedelta(seconds=301)
    corpus = await cache.obter()
    assert carregar.chamadas == 2
    assert corpus.carregado_em == AGORA + timedelta(seconds=301)


async def test_uma_carga_por_vez(config: Config) -> None:
    carregar = Carregador(_boa(), espera=0.05)
    cache = CacheCorpus(config, carregar=carregar, relogio=Relogio())
    await asyncio.gather(*(cache.obter() for _ in range(10)))
    assert carregar.chamadas == 1


async def test_carga_parcial_serve_mas_nao_guarda(config: Config) -> None:
    parcial = _boa()
    parcial.falhas = ["episodes"]
    carregar = Carregador(parcial, _boa())
    cache = CacheCorpus(config, carregar=carregar, relogio=Relogio())
    corpus = await cache.obter()
    assert corpus.faltando == ["episodes"]
    assert len(corpus.registros) == 1
    corpus = await cache.obter()
    assert carregar.chamadas == 2
    assert corpus.faltando == []


async def test_falha_total_com_cache_anterior_serve_o_anterior(config: Config) -> None:
    relogio = Relogio()
    carregar = Carregador(_boa(), _falha_total())
    cache = CacheCorpus(config, carregar=carregar, relogio=relogio)
    await cache.obter()
    relogio.agora = AGORA + timedelta(seconds=400)
    corpus = await cache.obter()
    assert len(corpus.registros) == 1
    assert corpus.carregado_em == AGORA
    assert corpus.faltando == list(CONSULTAS)


async def test_falha_total_sem_cache_levanta(config: Config) -> None:
    cache = CacheCorpus(config, carregar=Carregador(_falha_total()), relogio=Relogio())
    with pytest.raises(BaseIndisponivel):
        await cache.obter()


async def test_especialidades_conhecidas(config: Config) -> None:
    carga = _boa()
    carga.tabelas["content_relevance"] = [
        {"content_id": "x", "especialidade": "Radiologia", "score": 0.8},
        {"content_id": "y", "especialidade": "Cardiologia", "score": 0.9},
    ]
    cache = CacheCorpus(config, carregar=Carregador(carga), relogio=Relogio())
    corpus = await cache.obter()
    assert corpus.especialidades_conhecidas == ("Cardiologia", "Radiologia")
