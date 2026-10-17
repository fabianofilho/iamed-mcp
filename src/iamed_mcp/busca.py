"""Filtros, listagem e busca sobre o corpus em memória (puro, sem rede).

A busca compara sem acento dos dois lados, o que o ILIKE do Postgres não faz,
e segue o ranqueamento do chat do Hub do app: termo no título vale 3, no resumo
ou nas tags vale 1, mais um bônus de recência.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from iamed_mcp.corpus import Corpus, Registro, normalizar
from iamed_mcp.saida import Tipo

POUCOS_CLASSIFICADOS = 5
RECENCIA_DIAS = 90
RECENCIA_PESO = 2.0

PALAVRAS_VAZIAS: frozenset[str] = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas "
    "para pra com sem sobre entre e ou que qual quais como quando onde ao aos se sua seu suas "
    "seus mais menos muito novo nova novos novas ultimo ultima ultimos ultimas recente recentes "
    "recentemente saiu sairam tem ha the of and in on for to with".split()
)
# A base inteira é IA na medicina: estes termos casariam com tudo.
PALAVRAS_DO_DOMINIO: frozenset[str] = frozenset(
    "ia ai saude medicina medico medica medicos medicas clinica clinico clinicas clinicos "
    "inteligencia artificial health medicine medical".split()
)


@dataclass
class Pagina:
    """Uma página de resultados e os avisos para quem pediu."""

    registros: list[Registro]
    total: int
    pagina: int
    tem_mais: bool
    avisos: list[str] = field(default_factory=list)


def termos(tema: str) -> list[str]:
    """Termos úteis do tema: sem palavra vazia ou do domínio, sem o "s" final."""
    saida: list[str] = []
    for palavra in re.findall(r"[a-z0-9]+", normalizar(tema)):
        if palavra in PALAVRAS_VAZIAS or palavra in PALAVRAS_DO_DOMINIO:
            continue
        if len(palavra) > 3 and palavra.endswith("s"):
            palavra = palavra[:-1]
        if palavra not in saida:
            saida.append(palavra)
    return saida


def _padrao(termo: str) -> re.Pattern[str]:
    if len(termo) <= 3:
        return re.compile(rf"\b{re.escape(termo)}s?\b")
    return re.compile(rf"\b{re.escape(termo)}")


def _filtrar_especialidade(
    corpus: Corpus, registros: list[Registro], especialidade: str | None, avisos: list[str]
) -> list[Registro] | None:
    """Filtra por especialidade (nota do Jev). None quando a especialidade não existe."""
    if not especialidade:
        return registros
    alvo = normalizar(especialidade)
    nome = next((e for e in corpus.especialidades_conhecidas if normalizar(e) == alvo), None)
    if nome is None:
        conhecidas = ", ".join(corpus.especialidades_conhecidas) or "nenhuma"
        avisos.append(
            f"Especialidade '{especialidade[:60]}' não reconhecida. "
            f"Especialidades com itens classificados: {conhecidas}."
        )
        return None
    return [r for r in registros if nome in r.especialidades]


def _paginar(registros: list[Registro], limite: int, pagina: int, avisos: list[str]) -> Pagina:
    inicio = (pagina - 1) * limite
    return Pagina(
        registros=registros[inicio : inicio + limite],
        total=len(registros),
        pagina=pagina,
        tem_mais=inicio + limite < len(registros),
        avisos=avisos,
    )


def _aviso_poucos(especialidade: str | None, total: int, avisos: list[str]) -> None:
    if especialidade and total < POUCOS_CLASSIFICADOS:
        avisos.append(
            "Poucos itens da base estão classificados por especialidade. "
            "Para achar mais, use buscar com o tema (por exemplo, o nome da especialidade)."
        )


def _por_tipo(registros: list[Registro], tipos: list[Tipo] | None) -> list[Registro]:
    return [r for r in registros if not tipos or r.tipo in tipos]


def listar(
    corpus: Corpus,
    agora: datetime,
    *,
    tipos: list[Tipo] | None,
    dias: int,
    especialidade: str | None,
    escopo: str | None,
    limite: int,
    pagina: int,
) -> Pagina:
    """O que saiu na janela de `dias`, do mais novo para o mais antigo.

    Eventos e conferências entram também até `dias` à frente; os próximos vêm
    primeiro, do mais perto para o mais longe.
    """
    avisos: list[str] = []
    inicio, fim = agora - timedelta(days=dias), agora + timedelta(days=dias)
    candidatos: list[Registro] = []
    for r in _por_tipo(corpus.registros, tipos):
        if r.data is None or r.data < inicio:
            continue
        evento = r.tipo in ("evento", "conferencias")
        if r.data > (fim if evento else agora):
            continue
        if escopo and r.escopo != normalizar(escopo):
            continue
        candidatos.append(r)
    filtrados = _filtrar_especialidade(corpus, candidatos, especialidade, avisos)
    if filtrados is None:
        return _paginar([], limite, pagina, avisos)

    def chave(r: Registro) -> tuple[int, float]:
        assert r.data is not None
        if r.data > agora:
            return (0, (r.data - agora).total_seconds())
        return (1, (agora - r.data).total_seconds())

    filtrados.sort(key=chave)
    _aviso_poucos(especialidade, len(filtrados), avisos)
    return _paginar(filtrados, limite, pagina, avisos)


def buscar(
    corpus: Corpus,
    agora: datetime,
    *,
    tema: str,
    tipos: list[Tipo] | None,
    especialidade: str | None,
    dias: int | None,
    limite: int,
    pagina: int,
) -> Pagina:
    """Itens que casam com o tema, do mais relevante para o menos."""
    avisos: list[str] = []
    padroes = [_padrao(t) for t in termos(tema)]
    if not padroes:
        avisos.append(
            "O tema não tem palavras para buscar (só palavras genéricas como 'IA' ou "
            "'medicina'). Use um assunto mais específico ou listar_recentes."
        )
        return _paginar([], limite, pagina, avisos)

    candidatos = _por_tipo(corpus.registros, tipos)
    if dias is not None:
        inicio = agora - timedelta(days=dias)
        candidatos = [r for r in candidatos if r.data is not None and r.data >= inicio]
    filtrados = _filtrar_especialidade(corpus, candidatos, especialidade, avisos)
    if filtrados is None:
        return _paginar([], limite, pagina, avisos)

    pontuados: list[tuple[float, float, Registro]] = []
    for r in filtrados:
        pontos = 0.0
        for padrao in padroes:
            if padrao.search(r.titulo_norm):
                pontos += 3
            elif padrao.search(r.texto_norm):
                pontos += 1
        if pontos == 0:
            continue
        idade = (agora - r.data).total_seconds() / 86400 if r.data else float("inf")
        pontos += RECENCIA_PESO * max(0.0, 1 - max(idade, 0) / RECENCIA_DIAS)
        pontuados.append((pontos, r.data.timestamp() if r.data else 0.0, r))
    pontuados.sort(key=lambda t: (t[0], t[1]), reverse=True)
    resultado = [r for _, _, r in pontuados]
    _aviso_poucos(especialidade, len(resultado), avisos)
    return _paginar(resultado, limite, pagina, avisos)
