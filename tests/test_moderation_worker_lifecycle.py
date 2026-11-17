import asyncio
import logging
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from app import main as main_module
from app.settings import Settings


def _settings_from_env():
    return Settings(
        _env_file=None,
        postgres_password="unused-test-value",
        jwt_secret_key="unused-test-value",
    )


def _install_worker_mocks(monkeypatch):
    client = Mock()
    client.close = Mock()
    create_client = Mock(return_value=client)

    async def wait_until_shutdown(*_args):
        await asyncio.Event().wait()

    worker = AsyncMock(side_effect=wait_until_shutdown)
    monkeypatch.setattr(main_module, "create_openai_client", create_client)
    monkeypatch.setattr(main_module, "run_moderation_worker", worker)
    return client, create_client, worker


def test_worker_is_disabled_by_default_when_environment_flag_is_absent(
    monkeypatch, caplog
):
    monkeypatch.delenv("MODERATION_WORKER_ENABLED", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    settings = _settings_from_env()
    monkeypatch.setattr(main_module, "settings", settings)
    _client, create_client, worker = _install_worker_mocks(monkeypatch)

    assert settings.moderation_worker_enabled is False
    with caplog.at_level(logging.INFO, logger="app.main"):
        with TestClient(main_module.app):
            pass

    create_client.assert_not_called()
    worker.assert_not_awaited()
    assert "Moderation worker disabled" in caplog.text
    assert "test-key-never-sent" not in caplog.text


def test_worker_does_not_start_without_api_key_even_when_explicitly_enabled(
    monkeypatch, caplog
):
    monkeypatch.setenv("MODERATION_WORKER_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = _settings_from_env()
    monkeypatch.setattr(main_module, "settings", settings)
    _client, create_client, worker = _install_worker_mocks(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        with TestClient(main_module.app):
            pass

    assert settings.moderation_worker_enabled is True
    create_client.assert_not_called()
    worker.assert_not_awaited()
    assert "OPENAI_API_KEY is not configured" in caplog.text


def test_worker_starts_only_with_explicit_flag_and_api_key(monkeypatch):
    monkeypatch.setenv("MODERATION_WORKER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    settings = _settings_from_env()
    monkeypatch.setattr(main_module, "settings", settings)
    client, create_client, worker = _install_worker_mocks(monkeypatch)

    with TestClient(main_module.app):
        pass

    assert settings.moderation_worker_enabled is True
    create_client.assert_called_once_with()
    worker.assert_awaited_once_with(
        client,
        settings.moderation_worker_poll_seconds,
    )
    client.close.assert_called_once_with()
