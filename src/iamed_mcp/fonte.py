"""Leitura do espelho do Notion no Supabase, pela API REST, com a chave anon.

A lista de tabelas e colunas é fechada: nada fora de CONSULTAS é pedido, e o
corpo dos artigos e aulas (content_markdown), áudios e vídeos ficam de fora de
propósito. `articles.pdf_url` entra porque guarda a "URL Mídia" do Notion (a
página ou o DOI do artigo, medido em 18/10/2026: 293 de 293 externos); a saída
passa por `link_externo`, que recusa arquivo do storage e link do app. O
espelho só tem itens com Status publicado (filtro do sync-notion do app).

Erro de uma tabela não derruba a carga: vira uma entrada em `falhas`, e quem
monta o corpus decide o que fazer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from iamed_mcp.config import Config

logger = logging.getLogger(__name__)

CONSULTAS: dict[str, dict[str, str]] = {
    "articles": {
        "select": "id,title,summary,tags,published_at,pdf_url",
        "order": "published_at.desc.nullslast",
        "limit": "2000",
    },
    "notion_content": {
        "select": "id,tipo,titulo,resumo,tags,modulo,escopo,url_midia,data_publicacao",
        "tipo": "in.(news,evento,conferencias,repo)",
        "order": "data_publicacao.desc.nullslast",
        "limit": "2000",
    },
    "episodes": {
        "select": "id,title,description,spotify_url,published_at",
        "order": "published_at.desc.nullslast",
        "limit": "2000",
    },
    "lessons": {
        "select": "id,title,description,module,created_at",
        "order": "created_at.desc.nullslast",
        "limit": "2000",
    },
    "content_relevance": {
        "select": "content_id,especialidade,score",
        "score": "gte.0.7",
        "limit": "10000",
    },
}


@dataclass
class Carga:
    """Linhas de cada tabela que respondeu e o nome das que falharam."""

    tabelas: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    falhas: list[str] = field(default_factory=list)


async def _uma(cliente: httpx.AsyncClient, url: str, tabela: str) -> list[dict[str, Any]] | None:
    try:
        resposta = await cliente.get(f"{url}/rest/v1/{tabela}", params=CONSULTAS[tabela])
        resposta.raise_for_status()
        dados = resposta.json()
    except (httpx.HTTPError, ValueError) as erro:
        logger.warning("consulta %s falhou: %s", tabela, type(erro).__name__)
        return None
    if not isinstance(dados, list):
        logger.warning("consulta %s não devolveu lista", tabela)
        return None
    return [linha for linha in dados if isinstance(linha, dict)]


async def carregar_tabelas(config: Config, cliente: httpx.AsyncClient | None = None) -> Carga:
    """Lê as cinco tabelas em paralelo."""
    chave = config.supabase_anon_key.get_secret_value()
    cabecalhos = {"apikey": chave, "Authorization": f"Bearer {chave}"}
    url = config.supabase_url.rstrip("/")
    proprio = cliente is None
    cliente = cliente or httpx.AsyncClient(timeout=config.timeout_segundos)
    cliente.headers.update(cabecalhos)
    try:
        tabelas = list(CONSULTAS)
        resultados = await asyncio.gather(*(_uma(cliente, url, t) for t in tabelas))
    finally:
        if proprio:
            await cliente.aclose()
    carga = Carga()
    for tabela, linhas in zip(tabelas, resultados, strict=True):
        if linhas is None:
            carga.falhas.append(tabela)
        else:
            carga.tabelas[tabela] = linhas
    return carga
