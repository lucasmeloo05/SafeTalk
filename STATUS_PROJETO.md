# Status do projeto

**Última análise do código e consulta Alembic:** 10/11/2026.  
Este documento descreve o estado observado nessa análise; deve ser atualizado após mudanças verificadas.

## Resumo

O repositório contém uma API FastAPI com cadastro/login JWT, modelos SQLAlchemy para usuários, relacionamentos, servidores, conversas e mensagens, e migrações Alembic. A API operacional é bem menor que o conjunto de modelos e requisitos: existem endpoints para usuários, criação/listagem de conversas e envio/listagem de mensagens. Não foram encontrados frontend nem testes automatizados.

## Arquitetura observada

- **API:** `app/main.py`, FastAPI, versão declarada `0.3.0`.
- **Configuração e DB:** `app/settings.py`, `app/database.py`; SQLAlchemy com `postgresql+psycopg`, `pool_pre_ping` e sessões síncronas.
- **Autenticação:** `app/auth.py`; Bearer JWT HS256, usuário identificado pelo `sub`, conta deve existir e estar ativa.
- **Validação:** `app/schemas.py`, Pydantic v2.
- **Domínio:** `app/models/` possui 17 modelos/tabelas. As chaves estrangeiras existem, mas não há declarações ORM `relationship()`.
- **Rotas:** `app/routers/users.py`, `conversations.py`, `messages.py`.
- **Serviços:** `app/services/conversation_service.py`, `message_service.py`.
- **Banco local:** Docker Compose define PostgreSQL 17, volume persistente, healthcheck e publicação `5433:5432`. Não define serviço da API nem Dockerfile.
- **Dependências:** `requirements.txt` fixa versões de FastAPI, SQLAlchemy, Alembic, Psycopg, PyJWT, pwdlib e outras bibliotecas.

## Endpoints disponíveis observados

| Método e caminho | Comportamento observado | Autenticação |
|---|---|---|
| `GET /` | Mensagem e status da API | Não exigida |
| `GET /health` | Status estático `healthy` | Não exigida |
| `GET /health/database` | Executa `SELECT 1`; retorna 503 em erro SQLAlchemy | Não exigida |
| `POST /users/` | Cadastra usuário e cria configurações de privacidade padrão | Não exigida |
| `POST /users/login` | Aceita username ou e-mail e emite JWT válido por 30 minutos | Não exigida |
| `GET /users/me` | Retorna o usuário autenticado | Bearer JWT |
| `POST /conversations/direct` | Cria ou retorna conversa individual, aplicando bloqueio, amizade e preferência do destinatário | Bearer JWT |
| `GET /conversations/` | Lista conversas com participação ativa do usuário | Bearer JWT |
| `POST /conversations/{conversation_id}/messages` | Envia mensagem após verificar participação e bloqueio | Bearer JWT |
| `GET /conversations/{conversation_id}/messages` | Lista mensagens paginadas; aceita `limit` 1–100 e `offset` >= 0 | Bearer JWT |

## Modelos existentes

### Usuários e relacionamentos

`User`, `UserPrivacySettings`, `Friendship`, `Block`, `PlatformStaff`.

### Servidores

`Server`, `ServerMember`, `ServerRole`, `ServerMemberRole`, `ServerChannel`, `ServerInvite`, `ServerConfigHistory`.

### Conversas e mensagens

`Conversation`, `ConversationParticipant`, `ConversationInvitation`, `Message`, `MessageUserDeletion`.

Constraints existentes incluem unicidade de username/e-mail, não auto bloqueio, ordenação do par de amizade, estados permitidos em amizades/convites/participantes, unicidade de pares diretos, índices únicos parciais para participantes ativos e convites pendentes, validação de consistência da exclusão de mensagem e chave composta para assegurar que cargo e membro pertençam ao mesmo servidor. Isso não implementa por si só fluxos ou autorização da API.

## Funcionalidades efetivamente disponíveis na API

- Cadastro com username, e-mail, senha e data de nascimento; hash via `pwdlib.PasswordHash.recommended()` (Argon2 recomendado no ambiente atual); configurações de privacidade são criadas junto ao usuário.
- Validação de username de 3–30 caracteres alfanuméricos ou `_`; senha de 8–128 caracteres; e-mail validado por `EmailStr`; data não futura e ano >= 1900.
- Login por username/e-mail, verificação de senha, recusa de conta inativa e JWT HS256 com `sub`, `iat` e `exp` em 30 minutos.
- Leitura do perfil autenticado.
- Criação/recuperação de conversa direta: rejeita conversa consigo mesmo, destinatário inexistente/inativo, qualquer bloqueio entre os usuários e não amigos cujo destinatário não permita mensagens de desconhecidos.
- Envio de mensagem com conteúdo aparado, tamanho de 1–5000 caracteres no schema e verificação de participante ativo. Bloqueio impede envio em conversa direta.
- Listagem paginada de mensagens de conversa com participante ativo. Mensagens excluídas individualmente são omitidas; exclusão global existente no registro é apresentada com conteúdo substituído por `[Mensagem excluída]`.
- Listagem de conversas de que o usuário é participante ativo.

## Implementação parcial: modelos presentes, API incompleta

- **Amizades e bloqueios:** tabelas e constraints existem. Não há endpoints para gerenciar amizade/bloqueio. Bloqueios são consultados na abertura e no envio/listagem de conversa direta; amizades aceitas e privacidade do destinatário são consultadas ao criar conversa.
- **Privacidade:** preferências e defaults existem; não há API para lê-las ou atualizá-las. `allow_friend_requests`, `show_online_status` e `allow_group_invites` não são aplicados em rotas existentes.
- **Grupos:** tabelas de conversa, participante e convite existem; não há endpoint de criação ou gestão de grupos, participantes, papéis ou convites.
- **Servidores/canais/cargos:** modelos e migration existem; não há endpoints ou serviços operacionais de servidores, canais, cargos ou permissões.
- **Mensagens/exclusões:** envio e leitura estão disponíveis; existe tabela/campos para exclusão e timestamp de edição, mas não há endpoints/serviços para editar ou excluir, nem histórico de edição.
- **Verificação de conta:** `is_verified` existe no modelo/resposta, mas não há fluxo para verificar conta. Novos usuários não recebem verificação por este endpoint.

## Pendências de produto

- Gestão completa de grupos, incluindo convites e transferência de administração.
- Edição e exclusão de mensagens com regras de autoria, permissões, janela de 15 minutos e histórico.
- APIs para amizades, bloqueios e configurações de privacidade.
- APIs/operações para servidores, canais, cargos, permissões e convites.
- Denúncias, moderação humana/assistida por IA, histórico de penalidades e pontuação de segurança.
- Verificação de idade e acesso a espaços +18; autenticação em dois fatores.
- Upload/armazenamento de arquivos fora do PostgreSQL e funcionalidades de mídia.
- Voz em tempo real e WebRTC.
- Notificações, menções, busca, verificação de links e recursos planejados em [CONTEXTO_TCC.md](CONTEXTO_TCC.md).
- Frontend React/TypeScript/Vite/Tailwind.
- Testes automatizados abrangentes.

## Problemas técnicos observados

1. **Sem testes encontrados:** não foram encontrados arquivos ou diretórios de testes automatizados. Isso é uma lacuna de verificação, não prova de falha funcional específica.
2. **Sem `relationship()` ORM:** os modelos usam foreign keys, mas não declararam relacionamentos ORM. É uma característica/limitação atual, não necessariamente defeito por si só.
3. **Alembic offline:** `migrations/env.py` passa `config.get_main_option("sqlalchemy.url")` no modo offline, enquanto `alembic.ini` deixa essa URL vazia. A configuração offline precisa ser revisada antes de depender desse modo.
4. **Compose parcial:** o Docker Compose disponibiliza somente PostgreSQL. Não existe serviço de API/Dockerfile neste repositório.
5. **Reentrada em conversa direta:** o serviço retorna a conversa direta existente, mas não reativa participação marcada `LEFT`. O usuário pode receber a conversa sem participação ativa e continuar sem acesso. Problema real no comportamento do fluxo de criação/reuso.
6. **Bloqueio impede leitura do histórico:** `list_messages()` usa `check_direct_conversation_block()` assim como o envio. Isso impede ler o histórico quando há bloqueio e contraria a decisão de negócio de preservar o histórico acessível. Deve ser corrigido futuramente; não altera nem apaga registros.
7. **Documentação antiga diverge:** `docs/especificacao-tecnica.md` classifica conversas e mensagens como planejamento, embora haja modelos, migrations e parte dos endpoints. Tratar a documentação antiga como proposta, não como prova do estado atual.

## Migrações e banco observado

Foram encontrados seis arquivos de revisão Alembic encadeados:

1. `f46a25e64a14`: tabela de usuários.
2. `b3a25b568222`: data de nascimento de usuários.
3. `1b2711d27349`: privacidade, amizades, bloqueios e staff.
4. `457fe8255da3`: servidores, membros, cargos, canais, convites e histórico.
5. `cd34f0c32d15`: conversas, participantes e convites.
6. `bc365585aa97`: mensagens e exclusões individuais.

Consulta Alembic de somente leitura realizada em 10/11/2026 indicou `bc365585aa97 (head)`. Isso confirma a revisão declarada na tabela Alembic; não foi feita comparação completa do schema físico com a metadata. Nenhuma migração foi executada durante a análise.

## Verificação desta análise

- A análise foi estática sobre o código/configuração e a consulta de revisão atual foi somente leitura.
- Não foram executados testes automatizados.
- Nenhum arquivo foi alterado durante a análise que originou este status.
