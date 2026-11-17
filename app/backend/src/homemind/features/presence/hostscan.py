"""Varrimento Wi-Fi no ANFITRIÃO (modo `ingest`): `make presence-wifi-scan`.

O backend dentro do Docker (macOS/Windows) está numa rede virtual e não vê a tabela ARP do
anfitrião, por isso não encontra os telemóveis do hub. Este processo corre no anfitrião (ligado
ao Wi-Fi do hub), calcula os hashes dos MACs com o MESMO sal do backend e envia só os hashes.
Só biblioteca padrão. Nunca imprime MACs, IPs nem hashes.
"""

import argparse
import json
import logging
import time
import urllib.error
import urllib.request

from homemind.core.config import get_settings
from homemind.features.presence.wifi import ArpScanner, match_key

log = logging.getLogger("homemind.presence.hostscan")


def post_keys(url: str, token: str, keys: list[str]) -> None:
    req = urllib.request.Request(  # noqa: S310 - URL do operador (localhost por omissão)
        url.rstrip("/") + "/api/presence/wifi/observations",
        data=json.dumps({"keys": keys}).encode(),
        headers={"Content-Type": "application/json", "X-Presence-Token": token},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).close()  # noqa: S310


def scan_once(scanner: ArpScanner, salt: str, url: str, token: str) -> int:
    keys = sorted({match_key(salt, mac) for mac in scanner.scan()})
    post_keys(url, token, keys)
    return len(keys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8000", help="backend (porta do host)")
    ap.add_argument("--once", action="store_true", help="um varrimento e sai")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    s = get_settings()
    if not s.presence_wifi_collection_enabled:
        raise SystemExit("recolha desligada: PRESENCE_WIFI_COLLECTION_ENABLED=false em app/.env")
    if not (s.presence_match_salt and s.presence_ingest_token and s.presence_wifi_subnet):
        raise SystemExit(
            "falta PRESENCE_MATCH_SALT, PRESENCE_INGEST_TOKEN ou PRESENCE_WIFI_SUBNET em app/.env"
        )
    scanner = ArpScanner(s.presence_wifi_subnet)
    while True:
        try:
            n = scan_once(scanner, s.presence_match_salt, args.url, s.presence_ingest_token)
            log.info("varrimento enviado (%d aparelhos na rede)", n)
        except (OSError, urllib.error.URLError) as e:
            log.warning("varrimento não enviado (%s)", type(e).__name__)
        if args.once:
            return
        time.sleep(s.presence_wifi_interval_s)


if __name__ == "__main__":
    main()
