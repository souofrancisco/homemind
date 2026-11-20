# Conta Certa

**Aveiro Tech City Hackathon 2026 · Altice Labs — Connected Home**

*Cada um paga o que usa. A casa trata do resto.*

A **Conta Certa** ajuda moradores de casas partilhadas a compreender e repartir despesas de eletricidade. Combina medições de consumo, identificação provável de aparelhos e confirmação dos moradores para produzir faturas individuais explicáveis, acompanhar orçamentos e evitar divisões injustas.

## Começar

**Requisitos:** Docker com Compose v2, Make, [uv](https://docs.astral.sh/uv/) e Node.js 22+.

```bash
make setup       # Instalar dependências e configurar ambiente
make demo-up     # Iniciar a demonstração
```

A demo utiliza **dados simulados**, com autenticação local e regras de negócio executadas no backend.

| Serviço | Endereço |
|---|---|
| Aplicação | http://localhost:5173 |
| API / Swagger | http://localhost:8000/docs |
| Authentik | http://localhost:9000 |

As portas podem ser alteradas em `app/.env`.

### Contas de demonstração

| Utilizador | Papel |
|---|---|
| `ana`, `bruno`, `carla`, `diogo` | Moradores |
| `senhorio` | Gestão de faturas |
| `operador` | Operação |

**Palavra-passe:** `demo-conta-certa` (apenas ambiente local).

## Comandos

| Comando | Descrição |
|---|---|
| `make help` | Listar comandos principais |
| `make help-all` | Listar todos os comandos |
| `make setup` | Instalar dependências |
| `make demo-up` | Iniciar a demo |
| `make demo-reset` | Repor o cenário da demo |
| `make down` | Parar os serviços |
| `make auth-up` | Iniciar Authentik |
| `make backend` | Iniciar API com reload |
| `make frontend` | Iniciar frontend com hot reload |
| `make test` | Executar testes |
| `make lint` | Verificar código |
| `make check` | Executar verificações completas |
| `make build` | Gerar contratos e compilar frontend |

Para desenvolvimento manual:

```bash
make auth-up
make backend     # Terminal 1
make frontend    # Terminal 2
```

## Arquitetura

- **Frontend:** React 19, TypeScript, Vite e Mantine.
- **Backend:** Python 3.12, FastAPI e Pydantic.
- **Persistência:** SQLite e eventos de domínio.
- **Autenticação:** Authentik (OIDC).
- **Integração IoT:** MCP Altice, com adaptador de simulação FakeHome.

Os módulos comunicam através de contratos tipados e eventos. A identificação energética é probabilística; quando existe incerteza, o sistema utiliza as regras de atribuição da casa.

## Documentação

**[Documentação do projeto](https://souofrancisco.github.io/homemind/)**

- [Arquitetura](docs/architecture.md)
- [Desenvolvimento local](docs/development.md)
- [Funcionalidades e testes](docs/functional-flows.md)
- [Organização da equipa](docs/README.md)

**Nota:** a demo utiliza dados simulados. A integração completa com hardware real continua sujeita a validação.
