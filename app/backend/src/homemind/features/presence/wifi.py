"""Fonte Wi-Fi da presença: varrimento da rede do hub (ping + tabela ARP), só biblioteca padrão.

Privacidade (inegociável):
- o MAC existe só em memória, entre o varrimento e o hash (`match_key`); nunca é gravado, nem
  entra em logs, erros ou eventos;
- só os hashes de telemóveis registados com opt-in têm efeito; os restantes (visitas, vizinhos)
  são descartados sem rasto (nem o hash é guardado);
- a AUSÊNCIA de um telemóvel não é uma observação: este módulo só devolve o que viu.
"""

import hashlib
import hmac
import ipaddress
import platform
import re
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

_MAC = re.compile(r"\b([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})\b")
_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_MAC_STRICT = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
MAX_HOSTS = 1022  # /22: um varrimento maior não é «a rede do hub do kit»
_PING_WORKERS = 64


class WifiConfigError(ValueError):
    pass


def normalize_mac(raw: str) -> str:
    """`aa:bb:..` em minúsculas, 2 dígitos por byte (o macOS omite zeros à esquerda: `a:b:c`).
    Levanta ValueError se não for um MAC."""
    parts = raw.strip().lower().replace("-", ":").split(":")
    if len(parts) != 6 or not all(1 <= len(p) <= 2 for p in parts):
        raise ValueError("endereço inválido")
    mac = ":".join(p.zfill(2) for p in parts)
    if not _MAC_STRICT.match(mac):
        raise ValueError("endereço inválido")
    return mac


def match_key(salt: str, mac: str) -> str:
    """Pseudónimo estável do telemóvel: HMAC-SHA256(sal, MAC normalizado). O sal vem de
    `app/.env`; sem ele ninguém reverte o hash por força bruta sobre os 2^48 MACs."""
    if not salt:
        raise WifiConfigError("sal em falta")
    digest = hmac.new(salt.encode(), normalize_mac(mac).encode(), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def parse_neighbors(text: str) -> dict[str, str]:
    """{ip: mac normalizado} a partir da saída de `ip neigh` / `arp -an`. Ignora linhas sem MAC
    (`incomplete`, `(incomplete)`) e o endereço de difusão."""
    table: dict[str, str] = {}
    for line in text.splitlines():
        ip, mac = _IP.search(line), _MAC.search(line)
        if not (ip and mac):
            continue
        try:
            norm = normalize_mac(mac.group(1))
        except ValueError:
            continue
        if norm != "ff:ff:ff:ff:ff:ff":
            table[ip.group(1)] = norm
    return table


class WifiScanner(Protocol):
    """Devolve os MACs (normalizados) vistos agora na rede. Bloqueante: corre numa thread.
    Levanta se o varrimento falhar; nunca devolve «ninguém» para dizer «não sei»."""

    origin: str  # `real` | `simulated`

    def scan(self) -> set[str]: ...


class FakeWifiScanner:
    """SIMULADO (CI e demo): devolve os endereços fictícios que lhe derem."""

    origin = "simulated"

    def __init__(self, addresses: Iterable[str] = ()) -> None:
        self.addresses = {normalize_mac(a) for a in addresses}
        self.fail = False

    def scan(self) -> set[str]:
        if self.fail:
            raise OSError("varrimento simulado falhou")
        return set(self.addresses)


def hosts_of(subnet: str) -> list[str]:
    """Valida a sub-rede (só privada, no máximo /22) e lista os IPs a sondar."""
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        raise WifiConfigError("sub-rede inválida") from e
    if net.version != 4 or not net.is_private or net.is_loopback or net.is_link_local:
        raise WifiConfigError("só se varre uma rede privada IPv4")
    if net.num_addresses - 2 > MAX_HOSTS:
        raise WifiConfigError("sub-rede demasiado grande (máximo /22)")
    return [str(h) for h in net.hosts()]


def _ping(ip: str) -> bool:
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        r = subprocess.run(  # noqa: S603 - argumentos fixos; `ip` vem de ipaddress
            ["ping", flag, "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def _neighbors() -> dict[str, str]:
    for cmd in (["ip", "neigh"], ["arp", "-an"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout  # noqa: S603
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        table = parse_neighbors(out)
        if table:
            return table
    return {}


class ArpScanner:
    """REAL: ping a todos os IPs da sub-rede e leitura da tabela ARP do sistema onde corre.
    Só vê a rede onde a máquina está ligada (o Wi-Fi do hub): no Docker Desktop (macOS/Windows)
    o contentor está numa rede virtual e NÃO vê a ARP do anfitrião; correr no anfitrião."""

    origin = "real"

    def __init__(
        self,
        subnet: str,
        ping: Callable[[str], bool] = _ping,
        neighbors: Callable[[], dict[str, str]] = _neighbors,
    ) -> None:
        self._hosts = hosts_of(subnet)
        self._ping, self._neighbors = ping, neighbors

    def scan(self) -> set[str]:
        with ThreadPoolExecutor(_PING_WORKERS) as pool:
            alive = {
                ip
                for ip, ok in zip(self._hosts, pool.map(self._ping, self._hosts), strict=False)
                if ok
            }
        table = self._neighbors()
        # Só quem respondeu agora: uma entrada ARP antiga (aparelho que já saiu) não é presença.
        return {table[ip] for ip in alive if ip in table}
