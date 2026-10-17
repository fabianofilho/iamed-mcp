"""Filtros, listagem e busca em memória."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iamed_mcp.busca import buscar, listar, termos
from iamed_mcp.corpus import Corpus, Registro, normalizar
from iamed_mcp.saida import Tipo

AGORA = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_contador = 0


def reg(
    titulo: str,
    dias: float | None = 1,
    tipo: Tipo = "artigo",
    resumo: str = "",
    tags: tuple[str, ...] = (),
    especialidades: tuple[str, ...] = (),
    escopo: str | None = None,
) -> Registro:
    global _contador
    _contador += 1
    id_ = f"00000000-0000-4000-8000-{_contador:012d}"
    return Registro(
        id=id_,
        tipo=tipo,
        titulo=titulo,
        resumo=resumo,
        tags=tags,
        data=None if dias is None else AGORA - timedelta(days=dias),
        escopo=escopo,
        organizador=None,
        fonte=None,
        especialidades=especialidades,
        titulo_norm=normalizar(titulo),
        texto_norm=normalizar(" ".join([titulo, resumo, *tags])),
    )


def corpus(*registros: Registro, conhecidas: tuple[str, ...] = ("Radiologia",)) -> Corpus:
    return Corpus(
        registros=list(registros), carregado_em=AGORA, especialidades_conhecidas=conhecidas
    )


def _listar(c: Corpus, **kw: object) -> list[str]:
    params: dict[str, object] = dict(
        tipos=None, dias=14, especialidade=None, escopo=None, limite=20, pagina=1
    )
    params.update(kw)
    return [r.titulo for r in listar(c, AGORA, **params).registros]  # type: ignore[arg-type]


def _buscar(c: Corpus, tema: str, **kw: object) -> list[str]:
    params: dict[str, object] = dict(tipos=None, especialidade=None, dias=None, limite=10, pagina=1)
    params.update(kw)
    return [r.titulo for r in buscar(c, AGORA, tema=tema, **params).registros]  # type: ignore[arg-type]


# --- listar ----------------------------------------------------------------


def test_listar_janela_e_ordem() -> None:
    c = corpus(reg("velho", 20), reg("tres", 3), reg("um", 1), reg("sem data", None))
    assert _listar(c) == ["um", "tres"]


def test_listar_eventos_futuros_entram() -> None:
    c = corpus(
        reg("daqui 5", -5, tipo="evento"),
        reg("daqui 30", -30, tipo="evento"),
        reg("ha 2", 2, tipo="evento"),
        reg("artigo", 1),
    )
    titulos = _listar(c)
    assert "daqui 30" not in titulos
    assert titulos.index("daqui 5") < titulos.index("ha 2")
    assert set(titulos) == {"daqui 5", "ha 2", "artigo"}


def test_listar_filtra_tipos() -> None:
    c = corpus(reg("a", tipo="artigo"), reg("n", tipo="news"), reg("e", tipo="episodio"))
    assert set(_listar(c, tipos=["news", "episodio"])) == {"n", "e"}


def test_listar_filtra_escopo() -> None:
    c = corpus(
        reg("br", tipo="news", escopo="nacional"),
        reg("fora", tipo="news", escopo="internacional"),
        reg("sem", tipo="news"),
    )
    assert _listar(c, escopo="nacional") == ["br"]


def test_especialidade_sem_acento() -> None:
    c = corpus(
        reg("go", especialidades=("Ginecologia e Obstetricia",)),
        reg("outro"),
        conhecidas=("Ginecologia e Obstetricia",),
    )
    assert _listar(c, especialidade="ginecologia e obstetrícia") == ["go"]


def test_especialidade_desconhecida_avisa() -> None:
    c = corpus(reg("x", especialidades=("Radiologia",)), conhecidas=("Radiologia", "Cardiologia"))
    pagina = listar(
        c, AGORA, tipos=None, dias=14, especialidade="Ortopedia", escopo=None, limite=20, pagina=1
    )
    assert pagina.total == 0
    assert any("Radiologia" in a and "Cardiologia" in a for a in pagina.avisos)


def test_poucos_classificados_avisa() -> None:
    c = corpus(reg("a", especialidades=("Radiologia",)), reg("b", especialidades=("Radiologia",)))
    pagina = listar(
        c, AGORA, tipos=None, dias=14, especialidade="Radiologia", escopo=None, limite=20, pagina=1
    )
    assert pagina.total == 2
    assert any("buscar" in a for a in pagina.avisos)


def test_paginacao() -> None:
    c = corpus(*[reg(f"item {i}", i * 0.1) for i in range(5)])
    pagina = listar(
        c, AGORA, tipos=None, dias=14, especialidade=None, escopo=None, limite=2, pagina=2
    )
    assert [r.titulo for r in pagina.registros] == ["item 2", "item 3"]
    assert pagina.total == 5 and pagina.tem_mais and pagina.pagina == 2


def test_pagina_alem_do_fim() -> None:
    c = corpus(reg("a"), reg("b"))
    pagina = listar(
        c, AGORA, tipos=None, dias=14, especialidade=None, escopo=None, limite=20, pagina=20
    )
    assert pagina.registros == [] and pagina.total == 2 and not pagina.tem_mais


# --- buscar ----------------------------------------------------------------


def test_termos_descarta_vazias_e_dominio() -> None:
    assert termos("IA na saúde e medicina") == []
    assert termos("Modelos de linguagem") == ["modelo", "linguagem"]


def test_buscar_sem_acento_e_plural() -> None:
    c = corpus(reg("Ética em IA"), reg("Modelos de linguagem"), reg("Outra coisa"))
    assert _buscar(c, "etica") == ["Ética em IA"]
    assert _buscar(c, "modelo") == ["Modelos de linguagem"]


def test_buscar_inicio_de_palavra() -> None:
    c = corpus(reg("Radiologia torácica"), reg("Teleradiologia"))
    assert _buscar(c, "radiologia") == ["Radiologia torácica"]


def test_buscar_titulo_vale_mais_que_resumo() -> None:
    c = corpus(reg("Outro", 1, resumo="sepse no resumo"), reg("Sepse no título", 30))
    assert _buscar(c, "sepse") == ["Sepse no título", "Outro"]


def test_buscar_casa_tags() -> None:
    c = corpus(reg("Sem nada", tags=("Oncologia",)))
    assert _buscar(c, "oncologia") == ["Sem nada"]


def test_buscar_sigla_palavra_inteira() -> None:
    c = corpus(reg("Utilização de dados"), reg("UTI neonatal"))
    assert _buscar(c, "uti") == ["UTI neonatal"]


def test_buscar_so_palavras_do_dominio() -> None:
    c = corpus(reg("Saúde digital"), reg("Medicina e IA"))
    pagina = buscar(
        c,
        AGORA,
        tema="saúde medicina",
        tipos=None,
        especialidade=None,
        dias=None,
        limite=10,
        pagina=1,
    )
    assert pagina.registros == [] and pagina.total == 0
    assert any("tema" in a for a in pagina.avisos)


def test_buscar_respeita_dias_e_especialidade() -> None:
    c = corpus(
        reg("Sepse recente", 2, especialidades=("Radiologia",)),
        reg("Sepse antiga", 100, especialidades=("Radiologia",)),
        reg("Sepse sem especialidade", 2),
    )
    assert _buscar(c, "sepse", dias=30, especialidade="Radiologia") == ["Sepse recente"]


def test_buscar_empate_mais_novo_primeiro() -> None:
    c = corpus(reg("Sepse A", 200), reg("Sepse B", 150))
    assert _buscar(c, "sepse") == ["Sepse B", "Sepse A"]
