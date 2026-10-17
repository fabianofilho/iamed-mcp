"""Corpus em memória: as tabelas do espelho viram uma lista de registros.

A base é pequena (cerca de 1.000 itens em outubro de 2026), então o servidor
carrega tudo e filtra em memória. O cache vale 5 minutos e só uma carga roda por
vez: qualquer que seja o tráfego, o Supabase recebe no máximo cinco consultas a
cada 5 minutos.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from iamed_mcp.config import Config
from iamed_mcp.fonte import CONSULTAS, Carga, carregar_tabelas
from iamed_mcp.saida import Tipo, link_seguro, normalizar_id

logger = logging.getLogger(__name__)

_TIPOS_NOTION: dict[str, Tipo] = {
    "news": "news",
    "evento": "evento",
    "conferencias": "conferencias",
    "repo": "repo",
}
# A data destes é a do evento, que pode estar no futuro.
_DATA_DE_EVENTO: frozenset[str] = frozenset({"evento", "conferencias"})


def normalizar(texto: str) -> str:
    """Sem acento, minúsculo e com espaços colapsados, para comparar."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_marca = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_marca.lower().split())


@dataclass(frozen=True)
class Registro:
    """Um item da base, com o texto já normalizado para a busca."""

    id: str
    tipo: Tipo
    titulo: str
    resumo: str
    tags: tuple[str, ...]
    data: datetime | None
    escopo: str | None
    organizador: str | None
    fonte: str | None
    especialidades: tuple[str, ...]
    titulo_norm: str
    texto_norm: str


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _tags(valor: Any) -> tuple[str, ...]:
    if not isinstance(valor, list):
        return ()
    return tuple(t.strip() for t in valor if isinstance(t, str) and t.strip())


def _data(valor: Any) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=UTC)


def _escopo(valor: Any) -> str | None:
    texto = normalizar(_texto(valor))
    return texto if texto in ("nacional", "internacional") else None


@dataclass
class _Bruto:
    id: str
    tipo: Tipo
    titulo: str
    resumo: str
    tags: tuple[str, ...]
    data: datetime | None
    escopo: str | None = None
    organizador: str | None = None
    fonte: str | None = None


def _de_artigo(linha: dict[str, Any]) -> _Bruto:
    return _Bruto(
        id=_texto(linha.get("id")),
        tipo="artigo",
        titulo=_texto(linha.get("title")),
        resumo=_texto(linha.get("summary")),
        tags=_tags(linha.get("tags")),
        data=_data(linha.get("published_at")),
    )


def _de_notion(linha: dict[str, Any]) -> _Bruto | None:
    tipo = _TIPOS_NOTION.get(_texto(linha.get("tipo")))
    if tipo is None:
        return None
    tags = _tags(linha.get("tags"))
    modulo = _texto(linha.get("modulo")) or None
    organizador = None
    if modulo and tipo == "repo":
        # "GitHub, Python" vira tag, como no chat do Hub.
        extra = [p.strip() for p in modulo.replace(";", ",").split(",") if p.strip()]
        tags = tags + tuple(t for t in extra if t not in tags)
    elif modulo:
        organizador = modulo
    return _Bruto(
        id=_texto(linha.get("id")),
        tipo=tipo,
        titulo=_texto(linha.get("titulo")),
        resumo=_texto(linha.get("resumo")),
        tags=tags,
        data=_data(linha.get("data_publicacao")),
        escopo=_escopo(linha.get("escopo")),
        organizador=organizador,
        fonte=link_seguro(linha.get("url_midia")),
    )


def _de_episodio(linha: dict[str, Any]) -> _Bruto:
    return _Bruto(
        id=_texto(linha.get("id")),
        tipo="episodio",
        titulo=_texto(linha.get("title")),
        resumo=_texto(linha.get("description")),
        tags=(),
        data=_data(linha.get("published_at")),
        fonte=link_seguro(linha.get("spotify_url")),
    )


def _de_aula(linha: dict[str, Any]) -> _Bruto:
    return _Bruto(
        id=_texto(linha.get("id")),
        tipo="aula",
        titulo=_texto(linha.get("title")),
        resumo=_texto(linha.get("description")),
        tags=(),
        data=_data(linha.get("created_at")),
        organizador=_texto(linha.get("module")) or None,
    )


def _relevancia(linhas: list[dict[str, Any]]) -> dict[str, set[str]]:
    mapa: dict[str, set[str]] = {}
    for linha in linhas:
        id_ = normalizar_id(_texto(linha.get("content_id")))
        especialidade = _texto(linha.get("especialidade"))
        if id_ and especialidade:
            mapa.setdefault(id_, set()).add(especialidade)
    return mapa


def montar_registros(carga: Carga, agora: datetime) -> list[Registro]:
    """Converte as linhas em registros, sem duplicata, sem título vazio e sem futuro."""
    relevancia = _relevancia(carga.tabelas.get("content_relevance", []))
    brutos: list[_Bruto | None] = []
    brutos += [_de_artigo(linha) for linha in carga.tabelas.get("articles", [])]
    brutos += [_de_notion(linha) for linha in carga.tabelas.get("notion_content", [])]
    brutos += [_de_episodio(linha) for linha in carga.tabelas.get("episodes", [])]
    brutos += [_de_aula(linha) for linha in carga.tabelas.get("lessons", [])]

    vistos: set[str] = set()
    registros: list[Registro] = []
    for bruto in brutos:
        if bruto is None or not bruto.titulo:
            continue
        id_ = normalizar_id(bruto.id)
        if id_ is None or id_ in vistos:
            continue
        if bruto.data and bruto.data > agora and bruto.tipo not in _DATA_DE_EVENTO:
            continue
        vistos.add(id_)
        registros.append(
            Registro(
                id=id_,
                tipo=bruto.tipo,
                titulo=bruto.titulo,
                resumo=bruto.resumo,
                tags=bruto.tags,
                data=bruto.data,
                escopo=bruto.escopo,
                organizador=bruto.organizador,
                fonte=bruto.fonte,
                especialidades=tuple(sorted(relevancia.get(id_, ()))),
                titulo_norm=normalizar(bruto.titulo),
                texto_norm=normalizar(" ".join([bruto.titulo, bruto.resumo, *bruto.tags])),
            )
        )
    return registros


@dataclass
class Corpus:
    """Registros carregados, quando e o que faltou na carga."""

    registros: list[Registro]
    carregado_em: datetime
    faltando: list[str] = field(default_factory=list)
    especialidades_conhecidas: tuple[str, ...] = ()


class BaseIndisponivel(RuntimeError):
    """Nenhuma tabela respondeu e não há cache anterior para servir."""


Carregar = Callable[[Config], Awaitable[Carga]]


def _agora() -> datetime:
    return datetime.now(UTC)


class CacheCorpus:
    """Guarda o corpus por `config.cache_segundos`, com uma carga por vez."""

    def __init__(
        self,
        config: Config,
        carregar: Carregar = carregar_tabelas,
        relogio: Callable[[], datetime] = _agora,
    ) -> None:
        self._config = config
        self._carregar = carregar
        self._relogio = relogio
        self._ttl = timedelta(seconds=config.cache_segundos)
        self._bom: Corpus | None = None
        self._trava = asyncio.Lock()

    def _valido(self, agora: datetime) -> bool:
        return self._bom is not None and agora - self._bom.carregado_em < self._ttl

    async def obter(self) -> Corpus:
        """Corpus do cache, ou carregado agora se venceu."""
        if self._valido(self._relogio()):
            assert self._bom is not None
            return self._bom
        async with self._trava:
            agora = self._relogio()
            if self._valido(agora):
                assert self._bom is not None
                return self._bom
            carga = await self._carregar(self._config)
            if len(carga.falhas) >= len(CONSULTAS):
                logger.error("nenhuma tabela respondeu")
                if self._bom is None:
                    raise BaseIndisponivel("a base do IA.med está indisponível")
                return Corpus(
                    registros=self._bom.registros,
                    carregado_em=self._bom.carregado_em,
                    faltando=list(carga.falhas),
                    especialidades_conhecidas=self._bom.especialidades_conhecidas,
                )
            conhecidas = sorted(
                {
                    _texto(linha.get("especialidade"))
                    for linha in carga.tabelas.get("content_relevance", [])
                }
                - {""}
            )
            corpus = Corpus(
                registros=montar_registros(carga, agora),
                carregado_em=agora,
                faltando=list(carga.falhas),
                especialidades_conhecidas=tuple(conhecidas),
            )
            if not carga.falhas:
                self._bom = corpus
            return corpus
