"""Configuração do assistente (env). Local à feature; mesmos nomes de env que o motor antigo.

`features/engine/config.py` é REMOVE na migração: estes campos passam para `core/config` ou
ficam aqui (a decidir; ver docs/modules/agent.md).
"""

from functools import lru_cache

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


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
