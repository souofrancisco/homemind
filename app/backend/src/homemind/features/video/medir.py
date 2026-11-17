"""Mede a estabilidade da fonte de vídeo: `python -m homemind.features.video.medir --minutos 10`.

Lê `VIDEO_SOURCE` do ambiente. Não grava frames nem imprime o URL. Mede o lado do backend
(cadência e falhas); o atraso câmara->ecrã mede-se à parte, com um cronómetro em `GET /video`.
"""

import argparse
import time

from homemind.core.config import get_settings
from homemind.features.video.fonte import FonteRtsp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutos", type=float, default=10.0)
    parser.add_argument("--rotulo", default="fonte", help="ex.: principal, secundario")
    parser.add_argument("--intervalo", type=float, default=10.0, help="segundos entre linhas")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.video_source:
        raise SystemExit("VIDEO_SOURCE não está definido.")

    fonte = FonteRtsp(settings.video_source, sem_frame_s=settings.video_sem_frame_s)
    fonte.iniciar()
    inicio = time.monotonic()
    fim = inicio + args.minutos * 60
    proxima_linha = inicio + args.intervalo

    ultimo_indice, ultimo_t = 0, None
    total = janela = 0
    maior_intervalo = maior_intervalo_janela = 0.0
    quedas = 0  # transições camara_ok True -> False
    estava_ok = False
    resolucao = "?"

    try:
        while (agora := time.monotonic()) < fim:
            frame = fonte.ultimo_frame()
            if frame is not None and frame.indice != ultimo_indice:
                novos = frame.indice - ultimo_indice
                total += novos
                janela += novos
                if ultimo_t is not None:
                    intervalo = frame.t - ultimo_t
                    maior_intervalo = max(maior_intervalo, intervalo)
                    maior_intervalo_janela = max(maior_intervalo_janela, intervalo)
                ultimo_indice, ultimo_t = frame.indice, frame.t
                altura, largura = frame.imagem.shape[:2]
                resolucao = f"{largura}x{altura}"
            ok = fonte.camara_ok
            if estava_ok and not ok:
                quedas += 1
            estava_ok = ok
            if agora >= proxima_linha:
                print(
                    f"[{args.rotulo}] t={agora - inicio:6.0f}s  "
                    f"fps={janela / args.intervalo:5.1f}  "
                    f"maior_intervalo={maior_intervalo_janela * 1000:6.0f}ms  "
                    f"camara_ok={ok}  resolucao={resolucao}",
                    flush=True,
                )
                janela, maior_intervalo_janela = 0, 0.0
                proxima_linha += args.intervalo
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        fonte.parar()

    duracao = time.monotonic() - inicio
    print(
        f"RESUMO [{args.rotulo}] duracao={duracao:.0f}s  frames={total}  "
        f"fps_medio={total / duracao:.1f}  maior_intervalo={maior_intervalo * 1000:.0f}ms  "
        f"quedas={quedas}  resolucao={resolucao}"
    )


if __name__ == "__main__":
    main()
