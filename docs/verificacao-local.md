# Verificação local (16/10/2026)

Feita no MacBook, com a base real do IA.med (Supabase `iutwiaxeienjhvkvrcul`,
chave anon no `.env` local, fora do repositório). Clientes MCP de verdade:
Claude Code (`claude mcp add`) e MCP Inspector CLI 0.17.2.

## Base carregada

657 itens, nenhuma tabela faltando: 283 artigos, 227 news, 84 repositórios,
37 episódios, 18 eventos, 3 conferências, 5 aulas. 93 itens com especialidade
(nota do Jev >= 0,7), em 13 especialidades.

## Claude Code (stdio)

`claude mcp add iamed-local -s local -- uv --directory <pasta> run iamed-mcp`;
`claude mcp get iamed-local` mostrou `Status: ✔ Connected` (handshake real).
O `claude -p` não pôde chamar as tools nesta máquina porque a sessão OAuth do
CLI estava expirada (`Failed to authenticate`); as chamadas foram feitas pelo
Inspector, abaixo.

## MCP Inspector, stdio

- `tools/list`: `listar_recentes`, `buscar`, `abrir_item`, todas com
  `readOnlyHint: true`.
- `listar_recentes dias=7 limite=5`: total 18. Primeiro item: evento
  "Reinventing Clinical Guidelines in the AI Era" (21/10/2026,
  https://app.iamed.cc/eventos/3cb34afb-03ec-8141-a954-d55f04f692d0); depois
  repositórios de 15/10 (MediX-R1, EdgeCVS, EEG-DaSh, MedMNIST).
- `buscar tema=radiologia limite=3`: total 36. "HOPPR e CARPL.ai firmam
  parceria para IA de radiologia personalizável" (news, 08/10), "RSNA AI Deep
  Learning Lab 2026" (repo, 24/09), "O que ensinar aos residentes de
  radiologia quando o algoritmo também lê" (news, 04/09).
- `abrir_item` com o id da HOPPR: `encontrado: true`, resumo completo, fonte
  `http://www.itnonline.com/content/hoppr-carplai-announce-collaboration`,
  especialidades `["Radiologia"]`, tags `["IA", "Diagnóstico", "Deploy"]`.
- Toda resposta veio com o `aviso` de dado de terceiros.

## MCP Inspector, HTTP (`TRANSPORTE=streamable-http`, 127.0.0.1:8107/mcp)

- `listar_recentes tipos=["news"] dias=30 limite=3`: total 32. "Dois em cada
  três médicos ouvidos já usam IA, aponta pesquisa da MV" (15/10), "Modelos de
  IA avançam para prever sucesso da fertilização in vitro" (15/10),
  "Healthleap capta US$ 38 milhões..." (14/10), cada um com `link_app` e
  `fonte`.
- `buscar tema=sepse limite=3`: total 5; `abrir_item` do primeiro:
  `encontrado: true`.
- POST com `Host: atacante.exemplo`: **421** (proteção contra DNS rebinding).
- Log de uso no stderr, sem o texto do tema:
  `tool=buscar n=3 tipos=todos dias= especialidade= limite=3 pagina=1 tema_len=5 ms=1202 resultado=ok origem=127.0.0.0`.

## Testes automatizados

`make check`: ruff e mypy (strict) limpos, 117 testes passando.

## Depois da revisão final

- Página máxima real (`listar_recentes limite=50 dias=60`, total 203): 50
  itens, **93.948 bytes** na rede (POST direto ao endpoint), abaixo dos 100 KB.
- POST com corpo de 70 KB: **413**.
