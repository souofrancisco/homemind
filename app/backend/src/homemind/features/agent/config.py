"""Configuração do assistente (env), local à feature."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    # Nunca logar nem devolver este valor.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    agent_llm_timeout_s: float = 20.0
    agent_max_steps: int = 4
    # Prazo da resposta inteira (todos os passos); o efetivo é o menor entre este e timeout*passos.
    agent_total_timeout_s: float = 30.0
    # P-06 (que dados de consumo podem sair para o LLM) está por decidir: desligado por omissão.
    # Sem isto a ligado, o assistente nunca chama o LLM, mesmo com `NVIDIA_API_KEY` definida.
    agent_llm_enabled: bool = False
    agent_llm_scope: Literal["demo", "all"] = "demo"  # P-06: só a pergunta sai para o LLM
    # Ações propostas (AGENT-03). Os limites espelham `connectors/write_policy.RuleWriteLimits`
    # (MCP-04) sem a importar; aqui valem por dispositivo.
    agent_action_ttl_s: float = 600.0  # validade de uma proposta por confirmar
    agent_action_max_open: int = 3  # propostas por confirmar por residente
    agent_action_cooldown_s: float = 60.0  # entre duas execuções no mesmo dispositivo
    agent_action_max_per_hour: int = 6
    agent_action_lockout_s: float = 300.0  # bloqueio após um resultado incerto
    agent_action_timeout_s: float = 15.0  # prazo do executor; ao esgotar, resultado incerto
    # Histórico da conversa (#111): dados pessoais; retenção curta (P-25). Só para a app.
    agent_history_keep: int = 50  # mensagens guardadas por residente
    agent_history_days: int = 30  # idade máxima das mensagens


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
