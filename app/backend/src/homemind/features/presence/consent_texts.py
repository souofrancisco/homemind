"""Textos de consentimento por fonte (PRIV-03 #51). Fonte única: a API devolve-os e a app mostra-os,
por isso a versão que fica no registo corresponde ao texto que o morador leu.

Mudar QUALQUER texto exige mudar `TEXT_VERSION` (um teste fixa o conteúdo). Estes textos explicam
o que se recolhe, quem vê e como se revoga; **não são parecer jurídico nem afirmam conformidade
RGPD** (gate P-24 por decidir).
"""

from homemind.contracts.presence import ConsentSource

TEXT_VERSION = "2026-11-19.1"

_WHO = (
    "Só tu vês as tuas pistas e o teu estado. Os colegas e o senhorio não os veem. A casa usa o "
    "teu estado em casa/fora para a repartição das zonas comuns só se a regra da casa for «por "
    "presença» (só quando estás sozinho, sem visitas; na dúvida, por igual)."
)
_REVOKE = (
    "Podes desligar a qualquer momento em Definições. As pistas desta fonte são apagadas logo e "
    "as das outras fontes mantêm-se; o teu estado volta a calcular-se com o que sobra."
)

TEXTS: dict[ConsentSource, dict[str, str]] = {
    ConsentSource.wifi: {
        "title": "Wi-Fi do telemóvel",
        "collects": (
            "Regista que um telemóvel que registaste está ligado ao Wi-Fi da casa (guarda-se uma "
            "marca irreversível do aparelho, nunca o endereço de rede). Só conta como pista de "
            "que estás em casa; nunca como prova de que saíste. Ao desligar, os telemóveis "
            "registados também são removidos."
        ),
        "who_sees": _WHO,
        "how_to_revoke": _REVOKE,
    },
    ConsentSource.appliance: {
        "title": "Aparelho pessoal a ligar",
        "collects": (
            "Regista que um aparelho teu (declarado como pessoal) acabou de ligar numa tomada "
            "medida. Prova que estavas em casa a essa hora; um aparelho que já estava ligado não "
            "prova nada."
        ),
        "who_sees": _WHO,
        "how_to_revoke": _REVOKE,
    },
    ConsentSource.manual: {
        "title": "As tuas respostas a «Estás em casa?»",
        "collects": (
            "Permite que o sistema te pergunte «estás em casa?» quando as pistas se contradizem "
            "e que a tua resposta conte. É uma pergunta, nunca uma acusação. Sem esta fonte "
            "ligada não há perguntas."
        ),
        "who_sees": _WHO,
        "how_to_revoke": _REVOKE,
    },
}
