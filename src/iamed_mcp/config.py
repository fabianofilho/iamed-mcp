"""Configuração do servidor, lida do ambiente (.env).

O servidor só aceita a chave anon (ou publishable) do Supabase. Com ela o RLS
deixa ler as tabelas espelho de conteúdo publicado e mais nada de útil. A
service role passaria por cima do RLS, então a subida recusa qualquer chave que
não seja anon: um engano no .env não vira um servidor público com acesso a
dados de usuário.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ChaveRecusada(ValueError):
    """A chave do Supabase não é anon. A mensagem nunca traz a chave."""


def _payload_jwt(chave: str) -> dict[str, object] | None:
    partes = chave.split(".")
    if len(partes) != 3:
        return None
    meio = partes[1] + "=" * (-len(partes[1]) % 4)
    try:
        dados = json.loads(base64.urlsafe_b64decode(meio))
    except (binascii.Error, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def validar_chave_anon(chave: str) -> None:
    """Levanta ChaveRecusada se a chave não for anon ou publishable."""
    if chave.startswith("sb_publishable_"):
        return
    if chave.startswith("sb_secret_"):
        raise ChaveRecusada("SUPABASE_ANON_KEY é uma chave secreta; use a anon ou publishable")
    payload = _payload_jwt(chave)
    if payload is None:
        raise ChaveRecusada("SUPABASE_ANON_KEY não parece chave do Supabase")
    if payload.get("role") != "anon":
        raise ChaveRecusada("SUPABASE_ANON_KEY não é anon; o servidor só lê com a chave anon")


class Config(BaseSettings):
    """Valores lidos do .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = Field(default="https://iutwiaxeienjhvkvrcul.supabase.co")
    supabase_anon_key: SecretStr = Field(default=SecretStr(""))
    cache_segundos: int = Field(default=300, ge=1)
    timeout_segundos: float = Field(default=8.0, gt=0)
    log_level: str = Field(default="INFO")

    # --- modo connector (servidor HTTP público) ---
    transporte: Literal["stdio", "streamable-http"] = Field(default="stdio")
    http_host: str = Field(default="127.0.0.1")
    http_porta: int = Field(default=8107, ge=1, le=65535)
    http_path: str = Field(default="/mcp")
    http_stateless: bool = Field(default=True)
    # O teto global protege a máquina (o tráfego do Claude chega dos IPs da
    # Anthropic); o por origem pega quem chama direto.
    http_limite_global_por_minuto: int = Field(default=300, ge=1)
    http_limite_por_minuto: int = Field(default=60, ge=1)
    # Nomes públicos aceitos no cabeçalho Host (proteção contra DNS rebinding).
    http_hosts_publicos: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("http_hosts_publicos", mode="before")
    @classmethod
    def _dividir_hosts(cls, valor: object) -> object:
        """Aceita "a.exemplo,b.exemplo" do .env, não só lista JSON."""
        if isinstance(valor, str):
            return [p.strip() for p in valor.split(",") if p.strip()]
        return valor


def carregar_config() -> Config:
    """Lê a configuração e recusa chave que não seja anon."""
    config = Config()
    validar_chave_anon(config.supabase_anon_key.get_secret_value())
    return config
