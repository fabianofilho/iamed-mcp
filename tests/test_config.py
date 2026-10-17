"""Configuração e a recusa de chave privilegiada."""

from __future__ import annotations

import base64
import json

import pytest

from iamed_mcp.config import ChaveRecusada, carregar_config, validar_chave_anon


def _b64(dados: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(dados).encode()).rstrip(b"=").decode()


def _jwt(payload: dict[str, str]) -> str:
    return f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{_b64(payload)}.assinatura"


def test_aceita_publishable() -> None:
    validar_chave_anon("sb_publishable_abc123")


def test_aceita_jwt_anon() -> None:
    validar_chave_anon(_jwt({"role": "anon"}))


def test_recusa_secret() -> None:
    with pytest.raises(ChaveRecusada):
        validar_chave_anon("sb_secret_abc")


def test_recusa_jwt_service_role() -> None:
    with pytest.raises(ChaveRecusada):
        validar_chave_anon(_jwt({"role": "service_role"}))


def test_recusa_lixo_e_vazio() -> None:
    for chave in ["", "abc", "a.b", "a.b.c", _jwt({})]:
        with pytest.raises(ChaveRecusada):
            validar_chave_anon(chave)


def test_mensagem_nao_mostra_a_chave() -> None:
    with pytest.raises(ChaveRecusada) as erro:
        validar_chave_anon("sb_secret_valor_que_nao_pode_vazar")
    assert "valor_que_nao_pode_vazar" not in str(erro.value)


def test_config_le_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_x")
    monkeypatch.setenv("HTTP_HOSTS_PUBLICOS", "a.exemplo, b.exemplo")
    config = carregar_config()
    assert config.supabase_url == "https://exemplo.supabase.co"
    assert config.supabase_anon_key.get_secret_value() == "sb_publishable_x"
    assert config.http_hosts_publicos == ["a.exemplo", "b.exemplo"]
    assert config.http_porta == 8107
    assert config.http_limite_global_por_minuto == 300
    assert config.http_limite_por_minuto == 60
    assert config.cache_segundos == 300
    assert config.timeout_segundos == 8.0


def test_carregar_config_recusa_chave_privilegiada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_secret_x")
    with pytest.raises(ChaveRecusada):
        carregar_config()
