"""Login dos connectors pagos: token, plano e respostas HTTP do middleware."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec

from iamed_mcp.mcp_server.login import LoginSupabase, plano_efetivo

SUPA = "https://exemplo.supabase.co"
EMISSOR = f"{SUPA}/auth/v1"
RECURSO = "https://host.exemplo/iamed/mcp"
CHAVE = ec.generate_private_key(ec.SECP256R1())
OUTRA = ec.generate_private_key(ec.SECP256R1())


def _token(chave: Any = CHAVE, **muda: Any) -> str:
    agora = int(time.time())
    dados = {
        "iss": EMISSOR,
        "aud": "authenticated",
        "sub": "u1",
        "exp": agora + 600,
        "iat": agora,
        "role": "authenticated",
        "client_id": "cli",
    }
    dados.update(muda)
    dados = {k: v for k, v in dados.items() if v is not None}
    return jwt.encode(dados, chave, algorithm="ES256")


def _login(**kw: Any) -> LoginSupabase:
    return LoginSupabase(
        supabase_url=SUPA,
        chave_anon="anon",
        recurso=RECURSO,
        caminho_mcp="/mcp",
        buscar_chave=lambda _t: CHAVE.public_key(),
        **kw,
    )


def _perfil(mock: respx.MockRouter, **perfil: Any) -> respx.Route:
    return mock.get(f"{SUPA}/rest/v1/profiles").mock(
        return_value=httpx.Response(200, json=[perfil])
    )


# --- regra do plano, igual ao effectiveTier do app ---

AGORA = datetime(2026, 10, 18, tzinfo=UTC)
FUTURO = (AGORA + timedelta(days=5)).isoformat()
PASSADO = (AGORA - timedelta(days=5)).isoformat()


@pytest.mark.parametrize(
    ("plano", "status", "fim", "papel", "esperado"),
    [
        ("residente", "active", None, None, "residente"),
        ("doutor", "canceling", None, None, "doutor"),
        ("residente", "past_due", None, None, "residente"),
        ("residente", "canceled", FUTURO, None, "residente"),
        ("residente", "canceled", PASSADO, None, "interno"),
        ("interno", "trialing", FUTURO, None, "pos-doc"),
        ("interno", "trialing", PASSADO, None, "interno"),
        ("interno", "trialing", None, None, "pos-doc"),
        (None, None, None, "admin", "pos-doc"),
        (None, None, None, "creator", "pos-doc"),
        ("pos-doc", None, None, None, "interno"),
        (None, "active", None, None, "interno"),
        ("inventado", "active", None, None, "interno"),
    ],
)
def test_plano_efetivo(
    plano: str | None, status: str | None, fim: str | None, papel: str | None, esperado: str
) -> None:
    assert plano_efetivo(plano, status, fim, papel, agora=AGORA) == esperado


# --- conferir ---


@respx.mock
def test_aceita_residente() -> None:
    rota = _perfil(respx.mock, plan_tier="residente", subscription_status="active")
    resultado = asyncio.run(_login().conferir(_token()))
    assert resultado.id == "u1" and resultado.plano == "residente"  # type: ignore[union-attr]
    pedido = rota.calls.last.request
    assert (
        pedido.headers["authorization"].startswith("Bearer ") and pedido.url.params["id"] == "eq.u1"
    )


@respx.mock
def test_recusa_plano_interno_com_403() -> None:
    _perfil(respx.mock, plan_tier="interno", subscription_status=None)
    resultado = asyncio.run(_login().conferir(_token()))
    assert resultado.status == 403 and "app.iamed.cc/planos" in resultado.mensagem  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "token",
    [
        _token(OUTRA),  # assinado por outra chave
        _token(iss="https://outro/auth/v1"),  # outro emissor
        _token(aud="anon"),  # outra audiência
        _token(exp=int(time.time()) - 120),  # vencido além da folga
        _token(sub=None),  # sem sub
        jwt.encode({"sub": "u1"}, "s" * 32, algorithm="HS256"),  # algoritmo trocado
        "isto-nao-e-jwt",
    ],
)
def test_recusa_token_invalido_com_401(token: str) -> None:
    assert asyncio.run(_login().conferir(token)).status == 401  # type: ignore[union-attr]


def test_recusa_sessao_do_navegador_sem_client_id() -> None:
    resultado = asyncio.run(_login().conferir(_token(client_id=None)))
    assert resultado.status == 401 and "sessão" in resultado.mensagem  # type: ignore[union-attr]


@respx.mock
def test_supabase_fora_do_ar_da_503_e_nao_403() -> None:
    respx.get(f"{SUPA}/rest/v1/profiles").mock(return_value=httpx.Response(500))
    assert asyncio.run(_login().conferir(_token())).status == 503  # type: ignore[union-attr]


@respx.mock
def test_plano_fica_em_cache() -> None:
    rota = _perfil(respx.mock, plan_tier="residente", subscription_status="active")
    login = _login()
    asyncio.run(login.conferir(_token()))
    asyncio.run(login.conferir(_token()))
    assert rota.call_count == 1


def test_recurso_tem_que_terminar_no_caminho_do_mcp() -> None:
    with pytest.raises(ValueError):
        LoginSupabase(
            supabase_url=SUPA,
            chave_anon="a",
            recurso="https://h/iamed",
            caminho_mcp="/mcp",
            buscar_chave=lambda _t: None,
        )


# --- middleware ---


def _chamar(
    login: LoginSupabase, caminho: str = "/mcp", token: str | None = None
) -> tuple[int, dict, dict, list]:
    chegou: list[Any] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        chegou.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    enviado: list[dict] = []

    async def send(msg: dict) -> None:
        enviado.append(msg)

    cab = [(b"authorization", f"Bearer {token}".encode())] if token else []
    asyncio.run(login.proteger(app)({"type": "http", "path": caminho, "headers": cab}, None, send))
    inicio = enviado[0]
    cabecalhos = {k.decode(): v.decode() for k, v in inicio["headers"]}
    corpo = json.loads(enviado[1]["body"] or b"{}")
    return inicio["status"], cabecalhos, corpo, chegou


def test_metadata_fica_dentro_do_prefixo_e_sem_login() -> None:
    login = _login()
    status, _, corpo, chegou = _chamar(login, "/.well-known/oauth-protected-resource")
    assert status == 200 and chegou == []
    assert corpo["resource"] == RECURSO and corpo["authorization_servers"] == [EMISSOR]
    assert login.url_metadata == "https://host.exemplo/iamed/.well-known/oauth-protected-resource"


def test_sem_token_da_401_apontando_o_metadata() -> None:
    status, cab, _, chegou = _chamar(_login())
    assert status == 401 and chegou == []
    assert (
        'resource_metadata="https://host.exemplo/iamed/.well-known/oauth-protected-resource"'
        in cab["www-authenticate"]
    )


@respx.mock
def test_com_plano_chega_ao_app() -> None:
    _perfil(respx.mock, plan_tier="especialista", subscription_status="active")
    status, _, _, chegou = _chamar(_login(), token=_token())
    assert status == 200 and chegou == ["/mcp"]


@respx.mock
def test_sem_plano_da_403_e_nao_chega_ao_app() -> None:
    _perfil(respx.mock, plan_tier="interno")
    status, cab, _, chegou = _chamar(_login(), token=_token())
    assert (
        status == 403 and chegou == [] and 'error="insufficient_scope"' in cab["www-authenticate"]
    )


@respx.mock
def test_limite_por_usuario() -> None:
    _perfil(respx.mock, plan_tier="residente", subscription_status="active")
    login = _login(limite_por_usuario=2)
    assert [_chamar(login, token=_token())[0] for _ in range(3)] == [200, 200, 429]


def test_emissor_configuravel_vale_no_token_e_no_metadata() -> None:
    outro = "https://auth.exemplo/auth/v1"
    login = _login(emissores=[outro])
    assert login.metadata()["authorization_servers"] == [outro]
    assert asyncio.run(login.conferir(_token())).status == 401  # type: ignore[union-attr]


def test_config_divide_emissores(monkeypatch: pytest.MonkeyPatch) -> None:
    from iamed_mcp.config import Config

    monkeypatch.setenv("MCP_LOGIN_EMISSORES", "https://a/auth/v1, https://b/auth/v1")
    assert Config(_env_file=None).mcp_login_emissores == ["https://a/auth/v1", "https://b/auth/v1"]
