# Demonstração

!!! warning "Tudo é SIMULADO"
    A demonstração usa `FakeHome` e uma base de dados de demonstração. Nada foi validado com hardware real ponta a ponta. A interface rotula a origem de cada valor.

## Cenário

Casa de 4 moradores (Ana, Bruno, Carla e Diogo), fatura do mês de 120 €. Uma conta do senhorio e uma do operador completam o cenário.

A história: o Bruno tem um aquecedor de ~2000 W. Dividir 120 € por 4 daria 30 € a cada um, mas a Conta Certa mede, pergunta «De quem é esta conta?», atribui e explica cada recibo.

| Página | Conteúdo |
|---|---|
| [Percurso da aplicação](percurso.md) | O passo a passo em ~5 minutos |
| [Funcionalidades verificadas](verificado.md) | O que foi visto no browser, o que só tem testes, e a evidência |
| [Real, estimado e simulado](proveniencia.md) | Como se distinguem os dados |

## Arrancar a demonstração

```bash
make setup      # uma vez
make demo-up    # ~20 s: Authentik, contas, base de demo, backend e frontend
```

Aplicação em <http://localhost:5173>. `make demo-reset` repõe a base de demo; `make down` pára tudo. Detalhes em [Configuração local](../desenvolvimento/configuracao.md).

*Fontes canónicas: `README.md`, `docs/development/mvp.md`.*
