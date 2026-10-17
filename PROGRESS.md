# PROGRESS: iamed-mcp

## Objetivo
MCP somente leitura que expõe ao Claude o conteúdo publicado mais recente do
IA.med (listar, buscar, abrir item), sem dado de usuário. Spec aprovado em
16/10/2026: `docs/superpowers/specs/2026-10-16-iamed-mcp-design.md`.

## Estado (17/10/2026)
- Servidor implementado, 117 testes, ruff e mypy strict limpos.
- Testado local com a base real: MCP Inspector em stdio e HTTP; `claude mcp get`
  conectado. Detalhes em `docs/verificacao-local.md`.
- No ar desde 17/10/2026: `https://debian-f.tailf42a96.ts.net/iamed/mcp`. Checkout em
  `~/iamed-mcp` do debian-f (main, cab9d54), `.env` 600, unit de usuário
  `iamed-connector` com o drop-in `50-sandbox.conf` dos outros conectores (o processo
  só enxerga `~/iamed-mcp`). Conferido: tools/list e buscar pela URL pública (200),
  Host externo 421 no loopback, `origem=` no journal com o IP do cliente, anvisa e cfm
  seguem 200.
- Ainda sem conector no claude.ai e sem entrada no app.

## Próximos passos (cada um com ok do Fabiano)
1. ~~Clonar no debian-f, `.env`, `uv sync`~~ (feito 17/10).
2. ~~Unit + sandbox, testar em 127.0.0.1:8107~~ (feito 17/10).
3. ~~Rota `/iamed` no Funnel~~ (feito 17/10). Atualizar: `cd ~/iamed-mcp && git pull && ~/.local/bin/uv sync --frozen --no-dev && systemctl --user restart iamed-connector`.
4. Adicionar o conector no claude.ai e testar as três tools.
5. PR no med-ia-app: entrada em `web/src/lib/mcps.ts` e landing em
   iamed.cc/mcps; aviso de feature nova pela /push-iamed com texto aprovado.

## Decisões
Seções 3 e 12 do spec (acesso aberto, debian-f, repo público; espera de 30 s
após falha, tetos de resposta e corpo, unit sem EnvironmentFile).

## Restrições ativas
- Só chave anon; nunca service role. Somente leitura.
- Porta 8107 do debian-f reservada para este servidor.

## Fora do escopo
- `content_markdown` de `articles` e `lessons` legível pela anon no Supabase
  (vazio hoje): correção no med-ia-app, sessão separada.
- Token por usuário (v2, só se houver abuso).
- Menores adiados da revisão final: ver a seção 12 do spec e o PR.
