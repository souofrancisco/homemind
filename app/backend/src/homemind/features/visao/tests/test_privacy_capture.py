import asyncio
from types import SimpleNamespace

from homemind.contracts.home import EstadoCasa, EstadoLampada, EstadoTomada
from homemind.core.config import Settings
from homemind.features.visao import router


def test_dev_clip_never_drives_mcp_home(monkeypatch):
    settings = Settings(
        profile="demo", video_source="clip-sintetico.mp4", enable_dev_video_preview=True
    )
    monkeypatch.setattr(
        router, "VisaoSettings", lambda: SimpleNamespace(visao_detetor="detetor:Falso")
    )
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    monkeypatch.setattr(router.video, "fonte_dev_permitida", lambda _: True)
    monkeypatch.setattr(
        router,
        "carregar_detetor",
        lambda _: (_ for _ in ()).throw(AssertionError("detetor não devia carregar")),
    )
    casa_mcp = EstadoCasa(
        backend="mcp",
        mcp_ok=True,
        lampada=EstadoLampada(),
        tomada=EstadoTomada(),
        atualizado_em="2026-11-17T12:00:00Z",
    )
    fake_app = SimpleNamespace(
        state=SimpleNamespace(
            engine=SimpleNamespace(home_state=lambda: SimpleNamespace(backend=casa_mcp.backend))
        )
    )

    async def scenario():
        async with router.lifespan(fake_app):
            pass

    asyncio.run(scenario())
