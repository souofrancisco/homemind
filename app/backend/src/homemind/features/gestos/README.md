# Ponte de eventos

`ponte.py` mantém o adaptador genérico e thread-safe que publica eventos tipados numa fila
`asyncio.Queue`. Não há consumidor de produção registado atualmente; a ponte fica preservada
como KEEP no plano BASE-04. Os testes cobrem apenas a publicação e a segurança dos logs.
