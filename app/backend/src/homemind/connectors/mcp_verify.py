"""Verificação física controlada (#10/#11). Corre no host, com confirmação explícita do operador.

    make mcp-verify what=lamp     # lâmpada: cor/brilho de teste, releitura, restauro
    make mcp-verify what=plug     # tomada: desliga/liga, só com carga segura ligada

Usa um grant temporário privado (2 min, só o dispositivo testado), não o da demo. Nunca toca em
alarmes ou segurança: usa o mesmo `McpHome` e a mesma whitelist da aplicação. Sem IDs na saída.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from homemind.connectors.mcp_home import McpHome, _lamp_state, _rgb_confere, cor_verificavel
from homemind.connectors.write_grant import write_grant
from homemind.core.config import get_settings

TEST_COLOR = {"type": "color_rgb", "redValue": 255, "greenValue": 0, "blueValue": 0}
TEST_BRIGHTNESS = {"type": "brightness", "value": 40}


def _confirm(what: str, lines: list[str]) -> None:
    print("\nAlteração FÍSICA proposta:")
    for line in lines:
        print(f"  - {line}")
    if (
        input(f"Escreva AUTORIZO {what.upper()} para executar: ").strip()
        != f"AUTORIZO {what.upper()}"
    ):
        raise SystemExit("Não autorizado; nada foi alterado.")


def _escalar(e: Any) -> tuple[int, int, int]:
    return e.rgb or (255, 255, 255)


async def verify_lamp(home: McpHome) -> dict[str, Any]:
    await home._refrescar()
    inicial = (await home.estado()).lampada
    if not home._mcp_ok or "lamp" not in (home._ids or {}) or inicial.ligada is None:
        raise SystemExit(f"Lâmpada não descoberta inequivocamente. Aviso: {home._aviso}")
    print(f"Lâmpada descoberta. Estado inicial: {inicial.model_dump(mode='json')}")
    _confirm(
        "lampada",
        [
            "ligar a lâmpada, cor RGB(255,0,0) e brilho 40",
            "reler o estado físico e confirmar",
            f"restaurar o estado inicial ({inicial.model_dump(mode='json')})",
        ],
    )
    # Brilho antes da cor: escrever o brilho depois anula a cor (mcp-capabilities.md).
    test = [{"type": "power", "value": "on"}, TEST_BRIGHTNESS, TEST_COLOR]

    def aplicado(d: dict) -> bool:
        s = _lamp_state(d)
        return s.ligada is True and _rgb_confere(d, (255, 0, 0)) and s.brilho == 40

    result: dict[str, Any] = {"initial": inicial.model_dump(mode="json")}
    result["applied_confirmed"] = await home._escrever("lamp", test, aplicado)
    result["reread"] = (await home.estado()).lampada.model_dump(mode="json")
    result["failure_reason"] = home.ultima_falha
    # Restauro sempre tentado, mesmo que a alteração tenha falhado.
    restore: list[dict[str, Any]] = []
    if inicial.brilho:
        restore.append({"type": "brightness", "value": inicial.brilho})
    if inicial.rgb:
        r, g, b = inicial.rgb
        restore.append({"type": "color_rgb", "redValue": r, "greenValue": g, "blueValue": b})
    restore.append({"type": "power", "value": "on" if inicial.ligada else "off"})
    # A brilho baixo a cor lida não distingue cores: só se confirma ligada e brilho.
    cor_confirmavel = cor_verificavel(_escalar(inicial), inicial.brilho)
    result["restored_color_verified"] = cor_confirmavel

    def restaurado(d: dict) -> bool:
        s = _lamp_state(d)
        return s.ligada is inicial.ligada and (
            not inicial.ligada
            or (
                s.brilho == inicial.brilho
                and (not cor_confirmavel or _rgb_confere(d, _escalar(inicial)))
            )
        )

    result["restored_confirmed"] = await home._escrever("lamp", restore, restaurado)
    result["final"] = (await home.estado()).lampada.model_dump(mode="json")
    return result


async def verify_plug(home: McpHome) -> dict[str, Any]:
    await home._refrescar()
    if not home._mcp_ok or "plug" not in (home._ids or {}):
        raise SystemExit(f"Tomada não descoberta inequivocamente. Aviso: {home._aviso}")
    inicial = (await home.estado()).tomada.ligada
    print(f"Tomada descoberta. Estado inicial: ligada={inicial}")
    if inicial is None:
        raise SystemExit("Estado inicial desconhecido; abortado.")
    _confirm(
        "tomada",
        [
            f"{'desligar' if inicial else 'ligar'} a tomada (a carga ligada será afetada!)",
            "reler o estado físico e confirmar",
            f"restaurar o estado inicial (ligada={inicial})",
        ],
    )
    result: dict[str, Any] = {"initial_on": inicial}
    result["applied_confirmed"] = await home.definir_tomada(not inicial)
    result["failure_reason"] = home.ultima_falha
    result["restored_confirmed"] = await home.definir_tomada(inicial)
    result["final_on"] = (await home.estado()).tomada.ligada
    return result


async def main_async(what: str) -> None:
    base = get_settings()
    role = "lamp" if what == "lamp" else "plug"
    with tempfile.TemporaryDirectory() as tmp:
        # Grant privado e curto: só o dispositivo em teste.
        settings = base.model_copy(
            update={
                "enable_physical_writes": True,
                "mcp_write_grant_path": Path(tmp) / "grant.json",
            }
        )
        write_grant(settings.mcp_write_grant_path, 2, (role,), settings.mcp_write_max_minutes)
        home = McpHome(settings)
        run = verify_lamp if what == "lamp" else verify_plug
        result = await run(home)
    result["timings_ms"] = home.tempos_ms
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=("lamp", "plug"))
    asyncio.run(main_async(parser.parse_args().what))


if __name__ == "__main__":
    main()
