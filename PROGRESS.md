# PROGRESS: iamed-mcp

## Objetivo
MCP somente leitura que expõe ao Claude o conteúdo publicado mais recente do
IA.med (listar, buscar, abrir item), sem dado de usuário. Spec aprovado em
16/10/2026: `docs/superpowers/specs/2026-10-16-iamed-mcp-design.md`.

## Estado (16/10/2026)
- Servidor implementado, 117 testes, ruff e mypy strict limpos.
- Testado local com a base real: MCP Inspector em stdio e HTTP; `claude mcp get`
  conectado. Detalhes em `docs/verificacao-local.md`.
- Nada publicado: sem deploy no debian-f, sem rota no Funnel, sem entrada no app.

## Próximos passos (cada um com ok do Fabiano)
1. No debian-f (usuário f): clonar em `~/iamed-mcp` (checkout dedicado na
   main), `.env` com a chave anon (modo 600), `uv sync --frozen --no-dev`.
2. Instalar `deploy/iamed-connector.service`, subir e testar em 127.0.0.1:8107.
3. Abrir a rota `/iamed` no Funnel (`tailscale funnel --bg --set-path=/iamed
   http://127.0.0.1:8107`); conferir no journal que `origem=` varia por
   cliente, Host externo leva 421 e o público leva 200.
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
