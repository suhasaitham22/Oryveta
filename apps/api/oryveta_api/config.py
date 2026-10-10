"""Centralized runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://127.0.0.1:8000"
    database_path: str = ".oryveta/oryveta.db"
    github_client_id: str = ""
    github_client_secret: str = ""
    cookie_secure: bool = False
    local_demo: bool = False
    workspace_root: str = ".oryveta/workspaces"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""  # Explicit opt-in; no paid provider fallback.

    @classmethod
    def from_environment(cls) -> "Settings":
        base_url = os.environ.get("ORYVETA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        return cls(
            base_url=base_url,
            database_path=os.environ.get("ORYVETA_DATABASE_PATH", ".oryveta/oryveta.db"),
            github_client_id=os.environ.get("ORYVETA_GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("ORYVETA_GITHUB_CLIENT_SECRET", ""),
            cookie_secure=os.environ.get("ORYVETA_COOKIE_SECURE", "false").lower() == "true",
            local_demo=os.environ.get("ORYVETA_LOCAL_DEMO", "false").lower() == "true",
            workspace_root=os.environ.get("ORYVETA_WORKSPACE_ROOT", ".oryveta/workspaces"),
            ollama_url=os.environ.get("ORYVETA_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("ORYVETA_OLLAMA_MODEL", ""),
        )

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def demo_enabled(self) -> bool:
        url = urlsplit(self.base_url)
        return self.local_demo and url.hostname in {"localhost", "127.0.0.1", "::1"}

    def validate(self) -> None:
        url = urlsplit(self.base_url)
        if url.scheme not in {"http", "https"}:
            raise ValueError("Base URL must use HTTP or HTTPS")
        if url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            if url.scheme != "https" or not self.cookie_secure:
                raise ValueError("Public deployments require HTTPS and secure cookies")
        if bool(self.github_client_id) != bool(self.github_client_secret):
            raise ValueError("Provide both GitHub OAuth client ID and secret")
        if self.ollama_model:
            from oryveta_engine.model_runtime import OllamaProvider
            OllamaProvider(self.ollama_url, self.ollama_model)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.workspace_root).mkdir(parents=True, exist_ok=True)
