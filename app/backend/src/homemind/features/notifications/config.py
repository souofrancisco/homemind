"""Configuração local da feature (env). Sem `os.environ` espalhado; nada sensível."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class NotificationSettings(BaseSettings):
    # Cada quantos segundos se passam a `expired` as notificações abertas e vencidas. 0 desliga.
    notifications_expiry_sweep_s: float = 60.0


@lru_cache
def get_notification_settings() -> NotificationSettings:
    return NotificationSettings()
