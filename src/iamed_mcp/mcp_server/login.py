"""Login com a conta do IA.med para os connectors pagos.

Os connectors com acesso pago aceitam só quem entrou com a conta do app
(app.iamed.cc) e tem plano Residente ou acima, ou trial ativo. Quem emite o login
é o servidor OAuth 2.1 do Supabase do app; aqui só se confere o token.

**Por que um middleware próprio, e não o `token_verifier` do SDK.** O SDK publica
o metadata do recurso na raiz do host
(`/.well-known/oauth-protected-resource/iamed/mcp`, RFC 9728), e o Funnel só
encaminha o prefixo de cada servidor (`/iamed/*`). A descoberta daria 404. Aqui o
metadata fica dentro do prefixo e o `WWW-Authenticate` aponta para ele, que é o
endereço que o cliente segue.

**Por que o plano é lido com o token do próprio usuário.** A RLS do app só
devolve a linha do próprio usuário em `profiles`, e o banco não deixa ninguém
mudar o próprio plano. Com o token dele e a chave anon, o servidor lê o plano sem
chave de serviço e sem hook no Supabase.

**O token não é preso a este servidor.** O Supabase emite `aud = "authenticated"`,
igual à sessão comum do app. O `client_id` obrigatório separa o token OAuth da
sessão do navegador, mas um token entregue a outro cliente OAuth do mesmo projeto
abre estes servidores para a mesma pessoa. Detalhe em mcps-suite, docs/LOGIN.md.

Este arquivo é idêntico em todos os connectors com login: mude em um, copie nos
outros (o auditor da mcps-suite confere).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt

from .limite import LimitadorPorOrigem

logger = logging.getLogger(__name__)

# Ordem dos planos do app (med-ia-app, web/src/lib/tierAccess.ts, TIER_ORDER).
PLANOS = ("interno", "residente", "especialista", "doutor", "pos-doc")
PAGINA_DE_PLANOS = "https://app.iamed.cc/planos"
CAMINHO_METADATA = "/.well-known/oauth-protected-resource"
FOLGA_SEGUNDOS = 30
CACHE_PLANO_SEGUNDOS = 300

usuario_atual: contextvars.ContextVar[str] = contextvars.ContextVar("usuario", default="")


def plano_efetivo(
    plano: str | None,
    status: str | None,
    fim: str | None,
    papel: str | None,
    agora: datetime | None = None,
) -> str:
    """Mesma regra do `effectiveTier` do app. Mudou lá, muda aqui."""
    agora = agora or datetime.now(UTC)
    if papel in ("admin", "creator"):
        return "pos-doc"
    fim_dt = _data(fim)
    if status == "trialing" and (fim_dt is None or fim_dt > agora):
        return "pos-doc"
    ativo = status in ("active", "canceling", "past_due") or (
        status == "canceled" and fim_dt is not None and fim_dt > agora
    )
    if ativo:
        return plano if plano in PLANOS else "interno"
    return "interno"


def _data(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        valor = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=UTC)


def alcanca(plano: str, minimo: str) -> bool:
    return PLANOS.index(plano) >= PLANOS.index(minimo)


@dataclass(frozen=True)
class Recusa:
    status: int
    erro: str
    mensagem: str


@dataclass(frozen=True)
class Usuario:
    id: str
    plano: str


class LoginSupabase:
    """Confere o token OAuth do Supabase e o plano de quem chama."""

    def __init__(
        self,
        *,
        supabase_url: str,
        chave_anon: str,
        recurso: str,
        caminho_mcp: str,
        plano_minimo: str = "residente",
        emissores: list[str] | None = None,
        limite_por_usuario: int = 60,
        buscar_chave: Callable[[str], Any] | None = None,
        cliente: httpx.AsyncClient | None = None,
    ) -> None:
        if plano_minimo not in PLANOS:
            raise ValueError(f"plano_minimo desconhecido: {plano_minimo}")
        if not recurso.endswith(caminho_mcp):
            raise ValueError("o recurso tem que terminar no caminho do MCP")
        self.supabase_url = supabase_url.rstrip("/")
        self.chave_anon = chave_anon
        self.recurso = recurso
        self.plano_minimo = plano_minimo
        self.emissores = emissores or [f"{self.supabase_url}/auth/v1"]
        # O metadata fica no mesmo prefixo do MCP: .../iamed/mcp -> .../iamed/.well-known/...
        self.url_metadata = recurso[: -len(caminho_mcp)] + CAMINHO_METADATA
        if buscar_chave is None:
            jwks = jwt.PyJWKClient(
                f"{self.supabase_url}/auth/v1/.well-known/jwks.json", lifespan=3600
            )
            buscar_chave = jwks.get_signing_key_from_jwt
        self._buscar_chave = buscar_chave
        self._cliente = cliente
        self._planos: dict[str, tuple[float, str]] = {}
        self._limitador = LimitadorPorOrigem(limite_por_usuario)

    def metadata(self) -> dict[str, Any]:
        return {
            "resource": self.recurso,
            "authorization_servers": [self.emissores[0]],
            "bearer_methods_supported": ["header"],
            "resource_documentation": PAGINA_DE_PLANOS,
        }

    async def conferir(self, token: str) -> Usuario | Recusa:
        try:
            chave = await asyncio.to_thread(self._buscar_chave, token)
            dados = jwt.decode(
                token,
                getattr(chave, "key", chave),
                algorithms=["ES256"],
                audience="authenticated",
                issuer=self.emissores,
                leeway=FOLGA_SEGUNDOS,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError, OSError) as erro:
            logger.info("token recusado: %s", type(erro).__name__)
            return Recusa(401, "invalid_token", "token inválido ou vencido; conecte de novo")
        if not dados.get("client_id"):
            # Sessão do navegador, não token OAuth de um connector.
            return Recusa(401, "invalid_token", "use o login do connector, não a sessão do app")
        usuario = str(dados["sub"])
        try:
            plano = await self._plano(usuario, token)
        except httpx.HTTPError as erro:
            logger.warning("plano indisponível: %s", type(erro).__name__)
            return Recusa(
                503, "temporarily_unavailable", "não deu para conferir o plano agora; tente de novo"
            )
        if not alcanca(plano, self.plano_minimo):
            return Recusa(
                403,
                "insufficient_scope",
                f"este connector faz parte do plano {self.plano_minimo.capitalize()} "
                f"ou acima: {PAGINA_DE_PLANOS}",
            )
        return Usuario(usuario, plano)

    async def _plano(self, usuario: str, token: str) -> str:
        agora = time.monotonic()
        guardado = self._planos.get(usuario)
        if guardado and guardado[0] > agora:
            return guardado[1]
        cliente = self._cliente or httpx.AsyncClient(timeout=8)
        try:
            resposta = await cliente.get(
                f"{self.supabase_url}/rest/v1/profiles",
                params={
                    "id": f"eq.{usuario}",
                    "select": "plan_tier,subscription_status,subscription_end,role",
                },
                headers={"apikey": self.chave_anon, "authorization": f"Bearer {token}"},
            )
            resposta.raise_for_status()
        finally:
            if self._cliente is None:
                await cliente.aclose()
        linhas = resposta.json()
        perfil = linhas[0] if linhas else {}
        plano = plano_efetivo(
            perfil.get("plan_tier"),
            perfil.get("subscription_status"),
            perfil.get("subscription_end"),
            perfil.get("role"),
        )
        self._planos[usuario] = (agora + CACHE_PLANO_SEGUNDOS, plano)
        return plano

    def proteger(self, app: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
        """Embrulha o app ASGI: metadata aberto, todo o resto exige login e plano."""

        async def middleware(scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") != "http":
                await app(scope, receive, send)
                return
            if scope.get("path") == CAMINHO_METADATA:
                await _json(send, 200, self.metadata())
                return
            token = _token_do_cabecalho(scope)
            if token is None:
                await self._recusar(send, Recusa(401, "", "entre com a conta do IA.med"))
                return
            resultado = await self.conferir(token)
            if isinstance(resultado, Recusa):
                await self._recusar(send, resultado)
                return
            if not self._limitador.permitir(resultado.id):
                await _json(
                    send,
                    429,
                    {"erro": "limite de requisicoes excedido; tente em 1 minuto"},
                    [(b"retry-after", b"60")],
                )
                return
            marca = usuario_atual.set(resultado.id)
            try:
                await app(scope, receive, send)
            finally:
                usuario_atual.reset(marca)

        return middleware

    async def _recusar(self, send: Any, recusa: Recusa) -> None:
        partes = [f'resource_metadata="{self.url_metadata}"']
        if recusa.erro:
            partes.append(f'error="{recusa.erro}"')
        cabecalho = ("Bearer " + ", ".join(partes)).encode()
        await _json(
            send, recusa.status, {"erro": recusa.mensagem}, [(b"www-authenticate", cabecalho)]
        )


def _token_do_cabecalho(scope: Any) -> str | None:
    for nome, valor in scope.get("headers") or []:
        if nome.lower() == b"authorization":
            tipo, _, token = bytes(valor).decode("latin-1").partition(" ")
            if tipo.lower() == "bearer" and token.strip():
                return str(token.strip())
    return None


async def _json(
    send: Any, status: int, corpo: dict[str, Any], extras: list[tuple[bytes, bytes]] | None = None
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *(extras or [])],
        }
    )
    await send(
        {"type": "http.response.body", "body": json.dumps(corpo, ensure_ascii=False).encode()}
    )
