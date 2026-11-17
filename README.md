# SafeTalk

SafeTalk é uma plataforma de comunicação com foco em segurança, privacidade e moderação humana apoiada por ferramentas inteligentes. O projeto reúne uma API FastAPI, PostgreSQL e uma aplicação web React.

## Objetivo

O objetivo do SafeTalk é oferecer comunicação privada e recursos de comunidade com controles de autorização, preservação de evidências e revisão de denúncias. A análise automatizada é auxiliar: não aplica punições e não substitui a decisão humana.

## Estado funcional

### Implementado

- Cadastro, login JWT e perfil autenticado.
- Conversas privadas: criação/recuperação de conversa direta, listagem, leitura e envio de mensagens.
- Denúncia de mensagem privada por participante autorizado, com evidência baseada no registro original e preservada separadamente.
- Área oficial de denúncias: fila, detalhe/evidência, resultado da análise, triagem humana e decisão humana auditável.
- Análise externa pela OpenAI Moderation API (`omni-moderation-latest`) somente após triagem humana que a autorize. Suspeita de exploração sexual infantil registrada na triagem impede o envio externo e mantém o caso para revisão humana.
- Worker e fila persistente com tentativas limitadas, lease, recuperação e controle de concorrência. O resultado da IA é informativo; não há punição automática.
- Servidores: participação, cargos e permissões, hierarquia, convites, kick, ban, unban e consultas de auditoria.

### Parcial

- Há modelos de amizades, bloqueios e preferências de privacidade, e as regras existentes são aplicadas em operações de conversa. Não há APIs completas para gerenciar amizades, bloqueios ou todas as preferências.
- A interface oferece autenticação, conversas/mensagens privadas e painel oficial. O acesso oficial é sempre validado pelo backend; a proteção de rota no navegador não concede autorização.

### Planejado ou ainda ausente

- Transferência de propriedade de servidor, canais privados e mensagens em canais de servidor.
- Gestão completa de grupos, edição/exclusão de mensagens, anexos e mídia, voz em tempo real, notificações, verificação de idade e autenticação em dois fatores.
- Gestão de penalidades/appeals além do registro auditável de decisões humanas. A análise não executa sanções.

## Arquitetura e tecnologias

- **Backend:** Python 3.13 no ambiente local de referência, FastAPI, Pydantic, SQLAlchemy, Psycopg, Alembic e PostgreSQL 17.
- **Autenticação:** JWT Bearer; senhas são armazenadas com hash seguro.
- **Moderação:** SDK oficial OpenAI no backend e worker controlado por configuração de ambiente.
- **Frontend:** React, Vite, TypeScript, Tailwind CSS, React Router e Axios.
- **Desenvolvimento local:** Docker Compose para PostgreSQL; o frontend executa separadamente da API.

## Organização do repositório

```text
app/                    API, modelos, schemas, routers e serviços
migrations/             revisões Alembic
tests/                  testes backend
frontend/               aplicação React, serviços de API e testes Vitest
docker-compose.yml      PostgreSQL de desenvolvimento
docker-compose.test.yml PostgreSQL isolado para testes
requirements.txt        dependências Python da aplicação
requirements-test.txt   dependências adicionais de testes
```

## Pré-requisitos

- Docker Desktop com Docker Compose.
- Python 3.13 e `venv`.
- Node.js `^20.19.0` ou `>=22.12.0` e npm (requisito do Vite 8 usado pelo frontend).
- Chave da OpenAI somente se for habilitar o worker de moderação.

## Configuração local

O repositório não contém `.env.example` para o backend. Crie um arquivo `.env` local na raiz, que é ignorado pelo Git, com os valores de desenvolvimento apropriados:

```dotenv
POSTGRES_PASSWORD=defina-uma-senha-local
POSTGRES_USER=tcc_app
POSTGRES_DB=plataforma_tcc
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
JWT_SECRET_KEY=substitua-por-um-segredo-aleatorio-local
MODERATION_WORKER_ENABLED=false
MODERATION_WORKER_POLL_SECONDS=2
MODERATION_OPENAI_TIMEOUT_SECONDS=20
```

Gere um valor aleatório para `JWT_SECRET_KEY` localmente, por exemplo com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Não use valores reais de credenciais em arquivos versionados. As configurações de PostgreSQL têm defaults no código, mas `POSTGRES_PASSWORD` e `JWT_SECRET_KEY` são obrigatórios.

Para o frontend, configure `VITE_API_BASE_URL` em `frontend/.env.local`. O modelo `frontend/.env.example` usa `http://localhost:8000`:

```powershell
Copy-Item .env.example .env.local
```

Execute esse comando dentro de `frontend/`. O backend permite CORS para a origem local `http://localhost:5173`.

## PostgreSQL de desenvolvimento

Na raiz do repositório, com `.env` configurado:

```powershell
docker compose up -d postgres
```

O Compose publica o PostgreSQL 17 em `localhost:5433`, no banco definido por `POSTGRES_DB` (padrão `plataforma_tcc`). Para aplicar as migrations ao banco configurado, revise o destino e faça backup antes de executar:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Backend FastAPI

Na raiz do repositório:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

A API ficará em `http://localhost:8000`; a documentação Swagger estará em `http://localhost:8000/docs`. O servidor carrega as configurações do `.env`. O worker permanece desligado por padrão.

## Frontend React

Em outro terminal:

```powershell
Set-Location frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

A aplicação ficará em `http://localhost:5173`. Edite `frontend/.env.local` se a API não estiver em `http://localhost:8000`.

## Testes e build

Os testes backend são configurados para usar exclusivamente o PostgreSQL isolado do Compose de testes. Na raiz, instale as dependências adicionais e inicie o serviço de teste:

```powershell
python -m pip install -r requirements-test.txt
docker compose -f docker-compose.test.yml up -d postgres-test
python -m pytest -v
```

`tests/conftest.py` valida o banco, host, porta e usuário esperados e cria/remove as tabelas de teste; não aplica migrations. Não aponte `TEST_DATABASE_URL` para o banco de desenvolvimento.

Testes e build do frontend:

```powershell
Set-Location frontend
npm test
npm run build
```

## Worker e OpenAI Moderation API

O worker só inicia se `MODERATION_WORKER_ENABLED=true` **e** `OPENAI_API_KEY` estiver presente no ambiente do processo que inicia a API. A chave não é lida do bundle do frontend; mantenha-a fora do repositório e não a coloque em variáveis `VITE_*`. Para desenvolvimento, configure a chave como variável de ambiente de processo usando um método seguro do sistema operacional e inicie a API no mesmo processo/shell, por exemplo:

```powershell
$secureKey = Read-Host "Chave OpenAI" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
$env:MODERATION_WORKER_ENABLED = "true"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Depois de encerrar o servidor, remova as variáveis daquela sessão do PowerShell:

```powershell
Remove-Item Env:OPENAI_API_KEY, Env:MODERATION_WORKER_ENABLED
```

Mensagens privadas não são analisadas automaticamente. Somente uma denúncia persistida e aprovada pela triagem humana pode gerar análise externa; a suspeita de exploração sexual infantil registrada na triagem bloqueia o envio à OpenAI. A resposta do provedor é um sinal para revisão, e a decisão final é humana. Não há punição automática.
