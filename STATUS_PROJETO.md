# Status do projeto

**Última atualização do status:** 24/11/2026.

**Validação da entrega de mensagens em canais:** 686 testes backend aprovados no PostgreSQL isolado de testes (porta 55432), 204 testes frontend aprovados em 12 arquivos e build de produção aprovado. O teste da migration executou upgrade com canal preexistente, downgrade e novo upgrade em schema temporário do banco isolado.

**Validação histórica reportada em 20/11/2026:** backend com 630 testes aprovados, frontend com 87 testes aprovados e build de produção aprovado. A cadeia de migrations foi reportada como validada em PostgreSQL descartável até `a8c37d4e91b2`.
**Validação anterior:** `tests/test_social_api.py`: 16 passed no PostgreSQL isolado `plataforma_tcc_test` (`127.0.0.1:55432`); `social.test.tsx`: 4 passed; frontend completo: 50 passed em 8 arquivos; build aprovado. Esses resultados são históricos e foram substituídos pelos números acima.
**Validações históricas reportadas:** 32 testes backend aprovados nos testes de análise e API oficial; 32 testes frontend aprovados em 7 arquivos. Também foi reportado teste real da integração OpenAI em duas denúncias de exemplo, preservadas como evidências no banco de desenvolvimento; essa evidência não foi consultada nesta atualização.
**Última consulta ao estado Alembic do banco de desenvolvimento documentada:** 10/11/2026 (`bc365585aa97`, então head). A revisão `8a62d13e4f90` foi criada depois; o estado atual do banco de desenvolvimento não foi verificado nesta atualização documental.
Os números de 20/11 e os resultados anteriores foram preservados como histórico.

## Resumo

O repositório contém backend FastAPI com PostgreSQL, SQLAlchemy e Alembic, e frontend React/Vite/TypeScript/Tailwind. O backend oferece cadastro/login JWT, conversas e mensagens privadas, denúncia e moderação oficial, além dos módulos de servidores e funcionalidades sociais. O frontend conecta autenticação, conversas/mensagens, envio de denúncia, painel oficial e gestão de amizades e preferências disponíveis. Os resultados da última validação estão registrados acima.

## Arquitetura observada

- **API:** `app/main.py`, FastAPI, versão declarada `0.3.0`.
- **Frontend:** `frontend/`, React, Vite, TypeScript, Tailwind CSS, React Router e Axios; interface de autenticação, chat privado e moderação oficial.
- **Configuração e DB:** `app/settings.py`, `app/database.py`; SQLAlchemy com `postgresql+psycopg`, `pool_pre_ping` e sessões síncronas.
- **Autenticação:** `app/auth.py`; Bearer JWT HS256, usuário identificado pelo `sub`, conta deve existir e estar ativa.
- **Validação:** `app/schemas.py`, Pydantic v2.
- **Domínio:** `app/models/` contém modelos SQLAlchemy para usuários, conversas, servidores, convites e moderação. As chaves estrangeiras existem, mas não há declarações ORM `relationship()`.
- **Rotas:** além de usuários, conversas, mensagens, servidores, membros e cargos, `app/routers/server_moderation.py` expõe moderação e `app/routers/server_invites.py` expõe convites; ambos estão registrados em `app/main.py`.
- **Denúncias/moderação oficial:** `app/routers/reports.py` e `app/routers/official_reports.py` estão registrados em `app/main.py`; acesso às rotas oficiais exige `PlatformStaff` ativo e não revogado.
- **Análise externa:** `app/services/moderation_analysis_service.py` chama a OpenAI Moderation API (`omni-moderation-latest`) somente para tarefa elegível após triagem humana. O worker persistente fica desabilitado por padrão e requer `MODERATION_WORKER_ENABLED=true` e `OPENAI_API_KEY`.
- **Serviços:** `app/services/server_moderation_service.py` implementa kick, ban, unban e consultas de moderação; `app/services/server_invite_service.py` implementa criação, revogação, listagem e aceitação de convites. `app/server_permissions.py` define o catálogo reconhecido.
- **Especificação de autorização de servidores:** [ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md](ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md) registra regras aprovadas, estado implementado confirmado no código e pontos ainda pendentes.
- **Banco local:** Docker Compose define PostgreSQL 17, volume persistente, healthcheck e publicação `5433:5432`. Não define serviço da API nem Dockerfile.
- **Banco de testes:** `docker-compose.test.yml` define PostgreSQL 17 isolado, com container e volume próprios e porta `55432`; os testes usam `plataforma_tcc_test`.
- **Testes:** `pytest.ini`, `requirements-test.txt` e `tests/`; o `conftest.py` valida host local, porta, usuário e nome exato do banco de testes, substitui a dependência de banco da API e usa segredo JWT sintético. A fixture cria e remove as tabelas no banco de testes via metadata e reverte os dados de cada caso; não executa Alembic.
- **Servidores:** transferência de propriedade e canais públicos/privados com autorização por cargos estão implementados e possuem testes. Mensagens em canais estão disponíveis na API e nos detalhes do servidor.
- **Descoberta e entrada em servidores:** não há catálogo nem busca pública. `GET /servers/` retorna somente servidores nos quais o usuário autenticado possui participação `ACTIVE`, e conhecer um ID não concede acesso. A entrada e a reentrada exigem convite válido. `Server.is_discoverable` permanece como campo interno do modelo, sem efeito operacional e sem exposição em schemas ou respostas. O campo não integra `ServerCreate` nem `ServerUpdate`, que rejeitam campos extras.
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
| `GET /users/search` | Busca usernames públicos com paginação `limit` 1–100 e `offset` >= 0; exige ao menos 2 caracteres após trim e exclui o próprio usuário e bloqueios em qualquer direção | Bearer JWT |
| `GET /users/me/privacy` | Consulta as preferências de privacidade do usuário autenticado | Bearer JWT |
| `PATCH /users/me/privacy` | Atualiza parcialmente `allow_messages_from_strangers` e/ou `allow_friend_requests` do próprio usuário | Bearer JWT |
| `GET /social/friends` | Lista amizades aceitas paginadas | Bearer JWT |
| `GET /social/blocks` | Lista os usuários bloqueados pelo usuário autenticado | Bearer JWT |
| `PUT /social/blocks/{user_id}` | Bloqueia usuário e encerra relações pertinentes; não expõe publicamente a direção do bloqueio | Bearer JWT; ator vem do token |
| `DELETE /social/blocks/{user_id}` | Desbloqueia usuário sem restaurar amizades anteriores | Bearer JWT; ator vem do token |
| `GET /social/requests/received` | Lista solicitações recebidas paginadas | Bearer JWT |
| `GET /social/requests/sent` | Lista solicitações enviadas paginadas | Bearer JWT |
| `POST /social/requests` | Envia uma solicitação de amizade, sujeita a bloqueios e à preferência do destinatário | Bearer JWT |
| `POST /social/requests/{friendship_id}/accept` | Aceita uma solicitação recebida | Bearer JWT; participante da solicitação |
| `POST /social/requests/{friendship_id}/reject` | Recusa uma solicitação recebida | Bearer JWT; participante da solicitação |
| `DELETE /social/requests/{friendship_id}` | Cancela uma solicitação enviada | Bearer JWT; remetente da solicitação |
| `DELETE /social/friends/{user_id}` | Remove uma amizade aceita | Bearer JWT; participante da amizade |
| `POST /conversations/direct` | Cria ou retorna conversa individual, aplicando bloqueio, amizade e preferência do destinatário | Bearer JWT |
| `GET /conversations/` | Lista conversas com participação ativa do usuário | Bearer JWT |
| `POST /conversations/{conversation_id}/messages` | Envia mensagem após verificar participação e bloqueio | Bearer JWT |
| `GET /conversations/{conversation_id}/messages` | Lista mensagens paginadas; aceita `limit` 1–100 e `offset` >= 0 | Bearer JWT |
| `GET /conversations/{conversation_id}/messages/sync` | Sincroniza mensagens novas por cursor de criação | Bearer JWT; participante ativo e verificações de bloqueio |
| `GET /conversations/{conversation_id}/message-updates` | Pagina eventos de atualização e estado atual das mensagens | Bearer JWT; participante ativo e verificações de bloqueio |
| `PATCH /conversations/{conversation_id}/messages/{message_id}` | Edita mensagem do autor dentro de 15 minutos e emite evento | Bearer JWT; autoria, participação e bloqueios validados |
| `DELETE /conversations/{conversation_id}/messages/{message_id}` | Apaga globalmente mensagem do autor sem limite de tempo e emite evento | Bearer JWT; autoria, participação e bloqueios validados |
| `POST /servers/` | Cria servidor e participação ativa do proprietário na mesma transação | Bearer JWT |
| `GET /servers/` | Lista servidores com participação `ACTIVE` do usuário | Bearer JWT |
| `GET /servers/{server_id}` | Consulta servidor somente com participação ativa | Bearer JWT |
| `PATCH /servers/{server_id}` | Proprietário atualiza nome e descrição; campos de configuração e `owner_id` não são aceitos | Bearer JWT |
| `POST /servers/{server_id}/transfer-ownership` | Transfere propriedade a membro ativo não banido e registra auditoria | Bearer JWT; proprietário atual |
| `PATCH /servers/{server_id}/everyone-permissions` | Proprietário ativo substitui toda a configuração; registra valores anterior/novo em `ServerConfigHistory` atomicamente | Bearer JWT |
| `GET /servers/{server_id}/channels` | Lista canais visíveis, com paginação limitada | Bearer JWT; autorização por canal no serviço |
| `POST /servers/{server_id}/channels` | Cria canal | Bearer JWT; somente proprietário |
| `GET /servers/{server_id}/channels/{channel_id}` | Consulta canal conforme visibilidade e cargos autorizados | Bearer JWT; membro ativo autorizado ou proprietário |
| `PATCH /servers/{server_id}/channels/{channel_id}` | Atualiza canal/visibilidade e registra auditoria | Bearer JWT; somente proprietário |
| `DELETE /servers/{server_id}/channels/{channel_id}` | Exclui canal | Bearer JWT; somente proprietário |
| `PUT/DELETE /servers/{server_id}/channels/{channel_id}/roles/{role_id}` | Concede/remove acesso de cargo ao canal privado | Bearer JWT; somente proprietário |
| `GET /servers/{server_id}/members` | Lista membros `ACTIVE`, paginados, com dados mínimos | Bearer JWT e participação ativa do solicitante |
| `GET /servers/{server_id}/members/{user_id}` | Consulta um membro `ACTIVE` do servidor | Bearer JWT e participação ativa do solicitante |
| `POST /servers/{server_id}/leave` | Encerra a participação do usuário autenticado e limpa cargos individuais na mesma transação | Bearer JWT e participação ativa |
| `GET /servers/{server_id}/roles` | Lista cargos do servidor em ordem crescente de `position`, com `id` como desempate | Bearer JWT e participação ativa; não exige `manage_roles` |
| `GET /servers/{server_id}/roles/{role_id}` | Consulta cargo que pertence ao servidor da rota | Bearer JWT e participação ativa; não exige `manage_roles` |
| `POST /servers/{server_id}/roles` | Cria cargo comum sem atribuição automática | Bearer JWT; autorização no serviço |
| `PATCH /servers/{server_id}/roles/{role_id}` | Atualiza os campos permitidos do cargo | Bearer JWT; autorização no serviço |
| `DELETE /servers/{server_id}/roles/{role_id}` | Exclui cargo sem atribuições e registra auditoria | Bearer JWT; autorização no serviço; sucesso sem corpo (204) |
| `PUT /servers/{server_id}/members/{user_id}/roles/{role_id}` | Atribui cargo individual a membro | Bearer JWT; autorização no serviço |
| `DELETE /servers/{server_id}/members/{user_id}/roles/{role_id}` | Remove atribuição individual de cargo | Bearer JWT; autorização no serviço |
| `POST /servers/{server_id}/members/{user_id}/kick` | Expulsa membro ativo, encerra participação e audita | Bearer JWT; autorização e hierarquia no serviço; 204 |
| `POST /servers/{server_id}/members/{user_id}/ban` | Bane membro ativo, preserva snapshot e cria evento de auditoria | Bearer JWT; autorização e hierarquia no serviço; 201 |
| `GET /servers/{server_id}/bans` | Lista banimentos conforme autoridade do solicitante, com paginação | Bearer JWT; proprietário ou `unban_members` |
| `POST /servers/{server_id}/bans/{ban_id}/unban` | Revoga ciclo de banimento ativo sem reativar participação | Bearer JWT; autorização e hierarquia no serviço; 204 |
| `GET /servers/{server_id}/audit-logs` | Consulta eventos de moderação paginados, com filtros | Bearer JWT; exclusivo do proprietário |
| `POST /servers/{server_id}/invites` | Cria convite; token bruto aparece somente nesta resposta e o banco guarda seu hash | Bearer JWT; proprietário ou `manage_invites`; 201 |
| `POST /servers/{server_id}/invites/accept` | Aceita convite e cria ou reativa participação atomicamente | Bearer JWT; identidade do usuário autenticado |
| `GET /servers/{server_id}/invites` | Lista convites paginados sem expor token ou hash | Bearer JWT; proprietário ou `manage_invites` |
| `DELETE /servers/{server_id}/invites/{invite_id}` | Revoga convite pertencente ao servidor | Bearer JWT; proprietário ou `manage_invites`; 204 |
| `POST /reports` | Cria denúncia e snapshot da mensagem original; não inicia análise externa | Bearer JWT e participação na conversa |
| `GET /official/reports` | Lista denúncias paginadas com estado da triagem/análise | Bearer JWT e PlatformStaff ativo/não revogado |
| `GET /official/reports/{report_id}` | Consulta denúncia, evidência, análise e ações | Bearer JWT e PlatformStaff ativo/não revogado |
| `GET /official/reports/{report_id}/analysis` | Consulta estado e resultado da análise | Bearer JWT e PlatformStaff ativo/não revogado |
| `POST /official/reports/{report_id}/triage` | Registra triagem humana; aprovação pode tornar a tarefa elegível para análise externa | Bearer JWT e PlatformStaff ativo/não revogado |
| `POST /official/reports/{report_id}/decision` | Registra decisão humana auditável; não aplica punição automaticamente | Bearer JWT e PlatformStaff ativo/não revogado |

## Modelos existentes

### Usuários e relacionamentos

`User`, `UserPrivacySettings`, `Friendship`, `Block`, `PlatformStaff`.

### Servidores

`Server`, `ServerMember`, `ServerRole`, `ServerMemberRole`, `ServerChannel`, `ServerInvite`, `ServerConfigHistory`, `ServerBan`, `ServerAuditLog`.

`Server` possui `everyone_permissions` JSONB `NOT NULL`, default `{}` e constraint `ck_servers_everyone_permissions_object`. `ServerRole.is_system_role` também está presente, independente de `is_default`; ambos foram introduzidos pela revisão Alembic `8a62d13e4f90`, descendente de `bc365585aa97`. `is_default` e seu índice parcial permanecem sem função de negócio aprovada e não representam `@everyone` nem cargos reservados. A existência desses campos no modelo e na migration não confirma que a revisão foi aplicada ao banco de desenvolvimento.

`ServerRole.position` é inteiro não nulo, sem default Python ou de banco. O modelo inclui `ck_server_roles_position_positive` (`position >= 1`); posições repetidas são permitidas. A migration `990fa9af113d`, descendente de `8a62d13e4f90`, foi validada com upgrade e downgrade em PostgreSQL descartável; essa migration não foi aplicada aos bancos de desenvolvimento ou testes.

### Conversas e mensagens

`Conversation`, `ConversationParticipant`, `ConversationInvitation`, `Message`, `MessageUserDeletion`.

Constraints existentes incluem unicidade de username/e-mail, não auto bloqueio, ordenação do par de amizade, estados permitidos em amizades/convites/participantes, unicidade de pares diretos, índices únicos parciais para participantes ativos e convites pendentes, validação de consistência da exclusão de mensagem e chave composta para assegurar que cargo e membro pertençam ao mesmo servidor. Isso não implementa por si só fluxos ou autorização da API.

## Funcionalidades efetivamente disponíveis na API

- Cadastro com username, e-mail, senha e data de nascimento; hash via `pwdlib.PasswordHash.recommended()` (Argon2 recomendado no ambiente atual); configurações de privacidade são criadas junto ao usuário.
- Validação de username de 3–30 caracteres alfanuméricos ou `_`; senha de 8–128 caracteres; e-mail validado por `EmailStr`; data não futura e ano >= 1900.
- Login por username/e-mail, verificação de senha, recusa de conta inativa e JWT HS256 com `sub`, `iat` e `exp` em 30 minutos.
- Leitura do perfil autenticado.
- Criação/recuperação de conversa direta: rejeita conversa consigo mesmo, destinatário inexistente/inativo, qualquer bloqueio entre os usuários e não amigos cujo destinatário não permita mensagens de desconhecidos. Na reativação de participação `LEFT`, bloqueio e privacidade são verificados antes da alteração; se a solicitação for recusada, a participação permanece `LEFT`.
- Envio de mensagem com conteúdo aparado, tamanho de 1–5000 caracteres no schema e verificação de participante ativo. Bloqueio em qualquer direção impede envio em conversa direta.
- Listagem paginada de mensagens de conversa com participante ativo. Bloqueio em qualquer direção também impede consultar o histórico direto, sem apagar mensagens anteriores. Mensagens excluídas individualmente são omitidas; exclusão global existente no registro é apresentada com conteúdo substituído por `[Mensagem excluída]`.
- Listagem de conversas de que o usuário é participante ativo.
- Ao reusar uma conversa direta existente, a participação `LEFT` do solicitante pode ser reativada na mesma linha somente após as verificações de bloqueio, amizade e privacidade serem satisfeitas; o outro participante não é reativado automaticamente. Se houver bloqueio ou a privacidade do destinatário não permitir a conversa, a participação permanece `LEFT` e o histórico não é recuperado.
- CRUD básico de servidores: criação define proprietário pelo usuário autenticado e cria participação `ACTIVE` atomicamente; listagem e consulta exigem participação ativa; atualização de nome/descrição é exclusiva do proprietário.
- Resolução central de permissões: união dos grants booleanos de `everyone_permissions` e dos cargos individuais do membro `ACTIVE`; somente as seis chaves documentadas são reconhecidas. Proprietário é identificado separadamente; autorização de canais privados não é resolvida por esse serviço.
- Configuração de `@everyone`: `PATCH /servers/{server_id}/everyone-permissions` exige proprietário real com participação `ACTIVE`, substitui o objeto completo, aceita somente as seis permissões documentadas com valores booleanos estritos, rejeita chaves desconhecidas e aceita `{}`. Configuração e histórico de `ServerConfigHistory` são gravados na mesma transação; falha no histórico reverte a alteração. `manage_roles` não concede essa autoridade e `@everyone` não concede acesso a canais privados.
- Leitura de cargos: os endpoints `GET /servers/{server_id}/roles` e `GET /servers/{server_id}/roles/{role_id}` exigem JWT e participação `ACTIVE`, permitem acesso ao proprietário e a qualquer membro ativo sem `manage_roles`, e limitam resultados ao servidor informado. A consulta individual verifica `role_id` e `server_id`; a listagem ordena por `position` crescente e `id` como desempate. Os campos `is_default` e `is_system_role` são retornados independentemente, sem atribuição de nova semântica.
- CRUD e atribuições de cargos: `POST /servers/{server_id}/roles`, `PATCH /servers/{server_id}/roles/{role_id}`, `DELETE /servers/{server_id}/roles/{role_id}`, `PUT /servers/{server_id}/members/{user_id}/roles/{role_id}` e `DELETE /servers/{server_id}/members/{user_id}/roles/{role_id}` exigem JWT e delegam autorização ao serviço. O proprietário pode operar sobre cargos comuns sem `manage_roles` ou comparação numérica; membros comuns precisam estar ativos, possuir `manage_roles` e respeitar superioridade estrita. Criação/edição validam o catálogo de seis permissões, booleanos estritos, posição >= 1 e limites contra escalada. Criação não atribui automaticamente o cargo; edição é parcial e substitui integralmente o JSON de permissões enviado. Cargos `is_system_role=True` não podem ser editados/excluídos, nem pelo proprietário. Exclusão retorna 409 se houver qualquer associação, inclusive de membro LEFT, e grava snapshot atomicamente; edição também audita valores anteriores/novos. A atribuição/remoção manual está implementada com validação de ator, alvo, cargo, participação e hierarquia.
- Hierarquia: `get_member_hierarchy_level(db, server_id, user_id)` calcula o maior nível de cargos individuais para membro `ACTIVE`, ignorando `@everyone`; sem cargos retorna 0. `is_hierarchy_comparison_approved(db, server_id, actor_user_id, target_user_id)` valida ator e alvo `ACTIVE` no mesmo servidor (ausentes/LEFT resultam em 404). Proprietário passa sobre membro ativo independentemente da posição; membro comum precisa de posição estritamente superior e não pode agir sobre proprietário; autoação, igualdade ou nível inferior retorna `False`. A comparação não substitui a permissão específica e o ator vem do principal autenticado. O CRUD de cargos, a atribuição/remoção manual e os serviços de kick/ban/unban aplicam suas regras de autorização e hierarquia nos fluxos implementados.
- Moderação de membros: `POST /servers/{server_id}/members/{user_id}/kick`, `POST /servers/{server_id}/members/{user_id}/ban`, `POST /servers/{server_id}/bans/{ban_id}/unban`, `GET /servers/{server_id}/bans` e `GET /servers/{server_id}/audit-logs` estão implementados. As permissões `kick_members`, `ban_members` e `unban_members` são independentes; membros comuns também precisam de hierarquia estritamente superior, enquanto o proprietário usa autoridade especial. Kick encerra a participação e remove cargos sem banir; ban cria ciclo permanente, salva posição/snapshot e bloqueia reentrada; unban revoga sem reativar o membro nem restaurar cargos. Os eventos `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED` são registrados em `ServerAuditLog` na transação das operações. A lista de bans permite ao proprietário consultar ciclos ativos e revogados e a membros com `unban_members` somente os ativos; auditoria é exclusiva do proprietário.
- Convites: as quatro rotas HTTP de convite estão implementadas. Criação usa token criptograficamente seguro, persiste somente SHA-256 e retorna o segredo apenas uma vez; expiração, limite de usos e revogação são validados. Proprietário ou membro ativo com `manage_invites` pode criar, listar e revogar; a aceitação requer JWT e usa exclusivamente o usuário autenticado. A aceitação valida banimento ativo antes de consumir uso e, na mesma transação, cria participação ou reativa a linha `LEFT`, atualiza `joined_at`, limpa `left_at` e não restaura cargos. Convites expirados, revogados, esgotados ou associados a usuário banido não são consumidos.
- Denúncias e moderação oficial: `POST /reports` aceita somente referência da mensagem e motivo, busca a mensagem no banco, exige participação legítima, rejeita autodenúncia e duplicidade por denunciante/mensagem, e persiste denúncia/evidência/outbox atomicamente. O snapshot retém conteúdo original, autor e timestamps do modelo; a exclusão visível da mensagem não apaga a evidência. Não há análise automática no envio de mensagens privadas nem no ato de denunciar.
- Acesso oficial: os endpoints `/official/reports` usam a dependência de `PlatformStaff`, que exige estado `ACTIVE` e `revoked_at IS NULL`; isso é separado de cargos/permissões de servidor. O código atual não diferencia capacidades de `ADMIN` e `MODERATOR` nas operações da fila.
- Triagem e análise: toda tarefa nasce em `PENDING_TRIAGE`; sem aprovação humana a OpenAI não é chamada. A equipe pode recusar envio externo e manter a denúncia em revisão humana. A triagem também pode marcar suspeita de exploração sexual infantil, com justificativa; nesse caso a tarefa permanece inelegível e não é enviada à OpenAI. Não há classificador alternativo para reconhecer automaticamente esse conteúdo.
- Worker: a outbox persistente acompanha pendente, processamento, concluído, falha e revisão manual. Reivindicação transacional utiliza locks, `SKIP LOCKED`, lease e `claim_token`; tentativas são limitadas e leases vencidos podem ser recuperados. A chamada externa acontece fora da transação de banco e envia somente o snapshot da mensagem denunciada, sem histórico da conversa. Resultados armazenam modelo, flag geral, categorias, scores e tipos de entrada disponíveis. Erros não registram texto privado nem conteúdo do provedor nos logs. O worker não aplica sanções.
- Decisão humana e sanções: a equipe oficial registra decisão e justificativa em `ModerationAction`. Decisões humanas de advertência, suspensão ou banimento aplicam sanções no mesmo fluxo transacional; a IA não decide nem sanciona. Advertências válidas escalam para suspensão de sete dias e, na terceira, banimento permanente. Reversões e revisões de sanções derivadas são registradas sem apagar o histórico.

## Implementação parcial: modelos presentes, API incompleta

- **Amizades:** busca autenticada de usuários, envio, listagem paginada de amigos/solicitações, aceitação, recusa, cancelamento e remoção estão implementados nos endpoints `/users/search` e `/social/...`. A busca valida o mínimo após remover espaços, retorna dados públicos mínimos, pagina por `limit`/`offset` e considera somente relações `PENDING` ou `ACCEPTED`; relações `CANCELLED`, `REJECTED` ou `REMOVED` aparecem como `NONE`. A interface Pessoas oferece paginação para busca e listas, descarta respostas obsoletas e atualiza a solicitação aceita. O bloqueio tem endpoints próprios, descritos abaixo.
- **Privacidade:** `GET` e `PATCH /users/me/privacy` permitem ao usuário autenticado consultar e alterar `allow_messages_from_strangers` e `allow_friend_requests`. `show_online_status` e `allow_group_invites` existem no modelo, mas não têm API funcional confirmada.
- **Bloqueios:** criar, listar e remover bloqueios possui endpoints e interface. O bloqueio em qualquer direção impede início/reuso de conversa, envio e leitura de histórico; bloquear encerra amizades e solicitações pertinentes. O desbloqueio não restaura relações anteriores. Existem testes de API e concorrência.
- **Grupos:** tabelas de conversa, participante e convite existem; não há endpoint de criação ou gestão de grupos, participantes, papéis ou convites.
- **Servidores e participação:** criação, edição básica, listagem/consulta de membros ativos, saída, transferência de propriedade, CRUD/atribuição de cargos, permissões, canais públicos/privados, convites, kick/ban/unban e auditoria possuem implementação backend e testes. Mensagens em canais estão disponíveis na API e nos detalhes do servidor.
- **Mensagens:** envio, histórico, sincronização incremental, edição pelo autor em até 15 minutos e exclusão global pelo autor sem limite de tempo estão implementados. O cursor de eventos reflete atualizações de mensagens antigas; exclusão substitui o conteúdo visível, enquanto evidências de denúncia permanecem preservadas. O modelo e a filtragem de exclusão individual existem, mas não há operação HTTP confirmada para o usuário criar essa exclusão.
- **Denúncias/moderação:** denúncia de mensagens privadas, snapshot imutável, triagem humana, análise externa elegível, revisão oficial, ações e sanções progressivas estão implementadas. A IA não aplica sanções. Há reversão de sanções e revisão auditável de sanções derivadas. Apelações e um fluxo separado de incidentes não foram encontrados.
- **Verificação e idade:** o cadastro valida pelo menos 14 anos pela data declarada; o acesso +18 exige 18 anos no backend. `is_verified` permanece independente, sem verificação documental.

## Pendências de produto

- Verificação documental de identidade, além da autodeclaração disponível.
- Interface de administração completa de canais e política de retenção configurável.
- Gestão completa de grupos, incluindo criação, convites, participantes e papéis.
- Exclusão de contas e política de retenção/anonimização associada.
- Privacidade operacional de presença online (`show_online_status`) e de convites para grupos (`allow_group_invites`).
- Fluxo próprio de incidentes e apelações, se forem aprovados como requisitos de produto; hoje há denúncias, decisões e sanções, sem essas estruturas separadas.
- Definir a finalidade de `ServerRole.is_default` e quais cargos existentes devem receber `is_system_role`.
- Upload/armazenamento de arquivos fora do PostgreSQL e funcionalidades de mídia.
- Voz em tempo real e WebRTC.
- Notificações, menções, busca, verificação de links e recursos planejados em [CONTEXTO_TCC.md](CONTEXTO_TCC.md).
- Expansão do frontend e de sua cobertura conforme funcionalidades futuras; autenticação, chat privado e painel de moderação já existem.
- Ampliar a cobertura automatizada conforme novas funcionalidades forem implementadas; existem testes para convites, moderação, cargos e suas regras de concorrência.

## Problemas técnicos observados

1. **Sem `relationship()` ORM:** os modelos usam foreign keys, mas não declararam relacionamentos ORM. É uma característica/limitação atual, não necessariamente defeito por si só.
2. **Alembic offline:** `migrations/env.py` passa `config.get_main_option("sqlalchemy.url")` no modo offline, enquanto `alembic.ini` deixa essa URL vazia. A configuração offline precisa ser revisada antes de depender desse modo.
3. **Compose da API parcial:** o Docker Compose de desenvolvimento disponibiliza somente PostgreSQL. Não existe serviço da API/Dockerfile neste repositório. Há agora um Compose separado para PostgreSQL de testes.
4. **Documentação antiga diverge:** `docs/especificacao-tecnica.md` classifica conversas e mensagens como planejamento, embora haja modelos, migrations e parte dos endpoints. Tratar a documentação antiga como proposta, não como prova do estado atual.

## Correções recentes

- A leitura do histórico de uma conversa direta aplica a verificação de bloqueio após exigir participação ativa. Bloqueio em qualquer direção impede a consulta, mas não apaga mensagens anteriores.
- A reutilização de uma conversa direta pode reativar a participação `LEFT` do usuário solicitante, limpar `left_at`, preservar a conversa e suas mensagens e não reativar o outro participante. Bloqueio, amizade e privacidade são verificados antes da reativação; quando a solicitação é negada, a participação permanece `LEFT` e o histórico não pode ser recuperado.
- O CRUD básico de servidores foi implementado com autenticação JWT, autorização por participação ativa, atualização restrita ao proprietário e criação atômica de servidor/participação. Nenhuma migration foi necessária; os modelos e constraints existentes foram suficientes.
- O resolvedor central de permissões e a atualização integral de `everyone_permissions` foram implementados. A rota exige proprietário autenticado com participação `ACTIVE`, valida o catálogo e os booleanos, rejeita chaves desconhecidas e registra a mudança em `ServerConfigHistory` atomicamente.
- A leitura de cargos foi implementada com `GET /servers/{server_id}/roles` e `GET /servers/{server_id}/roles/{role_id}`. O router e o serviço usam a participação `ACTIVE` existente; a leitura não exige `manage_roles`, o cargo individual é limitado ao servidor da rota e a listagem tem ordenação estável por `position` e `id`.
- Arquivos dessa entrega: criados `app/routers/server_roles.py`, `app/services/server_role_service.py` e `tests/test_server_roles.py`; modificados `app/schemas.py` e `app/main.py`. Não foram necessárias migrations nem alterações nos modelos.
- A criação, edição e exclusão de cargos foram integradas às rotas POST/PATCH/DELETE, com autorização, hierarquia, limites de concessão, proteção de cargos de sistema e auditoria transacional de edição/exclusão. Os testes correspondentes estão em `tests/test_server_role_schema.py`, `tests/test_server_role_creation_service.py`, `tests/test_server_role_creation_api.py`, `tests/test_server_role_update_service.py`, `tests/test_server_role_update_api.py`, `tests/test_server_role_delete_service.py` e `tests/test_server_role_delete_api.py`; os testes de leitura permanecem em `tests/test_server_roles.py`. Nenhuma migration foi necessária para o CRUD de cargos.

## Especificação aprovada e estado de implementação

- As decisões da Etapa 2 estão consolidadas em `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md` e resumidas em `CONTEXTO_TCC.md`; requisitos não significam implementação. Saída, expulsão e banimento são distintos: saída/expulsão encerram participação como `LEFT`, limpam cargos e não banem; expulsão permite retorno por convite, enquanto banimento ativo impede entrada até revogação. Estão aprovadas as permissões independentes `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles`, além de `mention_everyone`, hierarquia estrita, posições a partir de 1 e exceções do proprietário. Membros comuns com `manage_roles` precisam respeitar hierarquia e só podem conceder permissões que já possuem efetivamente. `ServerRole.is_system_role` e `Server.everyone_permissions` estão no modelo e na revisão `8a62d13e4f90`; o resolvedor e a configuração owner-only também estão implementados. A classificação exata dos cargos reservados continua pendente. A atribuição/remoção de cargos, kick/ban/unban e convites têm serviços e rotas; os fluxos de reentrada por convite verificam banimentos ativos. `ServerBan` e `ServerAuditLog` são modelos e têm migration no código; isso não indica que a migration tenha sido aplicada ao banco de desenvolvimento. `@everyone` não concede acesso a canais privados.
- Além do CRUD básico e do núcleo de participação, estão implementados transferência de propriedade, CRUD e atribuição/remoção de cargos, resolvedor central, configuração owner-only de `everyone_permissions`, hierarquia, convites, kick/ban/unban, consultas de moderação/auditoria e canais privados com grants por cargo. Mensagens em canais estão disponíveis na API e nos detalhes do servidor.
- Decisões ainda abertas incluem a finalidade de `ServerRole.is_default`, a classificação concreta dos cargos `is_system_role`, eventual verificação documental de identidade, exclusão/anonimização de contas e o escopo de incidentes/apelações. Mensagens em canais estão disponíveis na API e nos detalhes do servidor. Já está implementado que somente o proprietário altera `everyone_permissions` e configura grants dos canais; `manage_roles` não concede essas autoridades e `@everyone` não dá acesso a canal privado.
- A análise estática encontrou `is_default` sem regra funcional; o preflight autorizado de leitura encontrou zero registros `is_default=true` e zero posições inválidas. A migration de posição `990fa9af113d` foi validada apenas em PostgreSQL descartável e não foi aplicada aos bancos de desenvolvimento ou testes.
- Há testes de serviço/API para CRUD de servidores, transferência de propriedade, canais privados, cargos, convites e moderação, inclusive cenários concorrentes. Mensagens em canais estão disponíveis na API e nos detalhes do servidor.

### Diferenças entre decisões e modelos atuais

- `Server.everyone_permissions` JSONB e a constraint de objeto estão no modelo e na revisão Alembic `8a62d13e4f90`; a rota de substituição integral, validação estrita, autorização owner-only e gravação transacional em `ServerConfigHistory` estão implementadas. A revisão no banco de desenvolvimento não foi verificada nesta atualização.
- `ServerChannel.is_private` e `ServerChannelRole` armazenam visibilidade e grants por cargo. O serviço aplica o acesso a membros ativos e ao proprietário, restringe configuração ao proprietário e audita mudanças de visibilidade e acesso.
- `ServerMemberRole` permite associações entre membros e cargos; saída, kick e ban removem atribuições no fluxo correspondente. A API oferece atribuição e remoção manual. Criação/edição/exclusão e atribuição/remoção aplicam autorização e hierarquia nos serviços; os serviços de kick/ban/unban também usam as permissões e a comparação hierárquica pertinentes.
- `ServerMember` representa participação `ACTIVE`/`LEFT`, `left_at` e unicidade `(server_id, user_id)`. Listagem/consulta, saída voluntária, expulsão, banimento e reentrada por convite estão implementados; reentrada atualiza a participação existente e não restaura cargos.
- O serviço central calcula a união de grants documentados de `everyone_permissions` e cargos individuais para membros ativos. As operações implementadas de cargos e moderação aplicam suas verificações de autorização/hierarquia e limites contra escalada conforme cada fluxo.
- Os limites aprovados para concessão de permissões (`manage_roles`, grants efetivos do ator, delta e validação dos membros afetados) são aplicados nos serviços de criação/edição e na atribuição de cargos; a remoção de atribuição também valida autorização e hierarquia.
- `ServerRole.is_default` é um booleano não nulo com default Python `False`; o índice único parcial `uq_server_roles_one_default` permite no máximo um cargo marcado por servidor. Não há lógica de autorização que o use; a resposta o expõe sem nova semântica. A migration original não define default no banco. `@everyone` é distinta em `Server.everyone_permissions`. `ServerRole.is_system_role` é independente e a proteção backend contra edição/exclusão está implementada para registros marcados; a lista/classificação exata e o mapeamento continuam pendentes.
- `ServerRole.position` é inteiro não nulo sem default Python ou de banco; o modelo e a revisão `990fa9af113d` impõem `position >= 1` com `ck_server_roles_position_positive`. Posições iguais são permitidas. O cálculo e a comparação hierárquica centralizada estão implementados e utilizados pelos serviços de cargos e moderação.
- Os modelos `ServerBan` e `ServerAuditLog`, a transferência de propriedade, os canais privados e seus serviços/rotas estão no código. Mensagens em canais estão disponíveis na API e nos detalhes do servidor.
- Esses pontos são lacunas de implementação/modelagem. A etapa de CRUD básico usou o schema existente e não criou migration.

## Migrações e banco observado

A cadeia de revisões Alembic presente no repositório contém dezoito arquivos e, pela inspeção dos `down_revision`, forma uma sequência linear até `a8c37d4e91b2`:

1. `f46a25e64a14`: tabela de usuários.
2. `b3a25b568222`: data de nascimento de usuários.
3. `1b2711d27349`: privacidade, amizades, bloqueios e staff.
4. `457fe8255da3`: servidores, membros, cargos, canais, convites e histórico.
5. `cd34f0c32d15`: conversas, participantes e convites.
6. `bc365585aa97`: mensagens e exclusões individuais.
7. `8a62d13e4f90`: adiciona `ServerRole.is_system_role`, `Server.everyone_permissions` JSONB e `ck_servers_everyone_permissions_object`; sua revisão anterior é `bc365585aa97`.
8. `990fa9af113d`: adiciona `ck_server_roles_position_positive` (`position >= 1`); sua revisão anterior é `8a62d13e4f90`.
9. `d8f4c2b19a70`: cria `server_bans` e `server_audit_logs`; sua revisão anterior é `990fa9af113d`.
10. `a14c77b204fe`: cria denúncias e evidências; sua revisão anterior é `d8f4c2b19a70`.
11. `e3810d7bc42a`: acrescenta metadados históricos ao snapshot da mensagem denunciada; sua revisão anterior é `a14c77b204fe`.
12. `f6a4c20d93b1`: cria a fila persistente de análise; sua revisão anterior é `e3810d7bc42a`.
13. `c7a91d52e604`: cria o contador e os eventos de atualização de mensagens; sua revisão anterior é `f6a4c20d93b1`.
14. `ee65b71a98a3`: cria o histórico interno de edições; sua revisão anterior é `c7a91d52e604`.
15. `9fb23a71c8d0`: vincula o histórico de edição ao evento da mesma mensagem; sua revisão anterior é `ee65b71a98a3`.
16. `c2f8a41d6b93`: acrescenta evento de transferência de propriedade à auditoria de servidor; sua revisão anterior é `9fb23a71c8d0`.
17. `d7af10e95bc2`: cria canais privados e eventos históricos de acesso; sua revisão anterior é `c2f8a41d6b93`.
18. `a8c37d4e91b2`: acrescenta decisões e sanções de moderação da plataforma; sua revisão anterior é `d7af10e95bc2`.

Consulta somente leitura ao banco de desenvolvimento realizada em 10/11/2026 indicou `bc365585aa97 (head)`, antes da criação da revisão `8a62d13e4f90`. Isso é um registro histórico, não uma confirmação do estado atual do banco. Esta atualização documental não consultou banco nem executou migration; portanto, o estado atual do banco de desenvolvimento permanece não verificado.

## Verificação desta análise

- Última regressão completa reportada antes desta atualização: **630 testes backend aprovados**, **87 testes frontend aprovados** e build de produção aprovado. A cadeia Alembic foi reportada validada em PostgreSQL descartável até `a8c37d4e91b2`. Esses resultados são históricos informados e não foram reexecutados nesta atualização documental.
- A URL de testes é validada pelo `tests/conftest.py` para `plataforma_tcc_test`, host local, porta 55432 e usuário `tcc_test`; o banco de desenvolvimento na porta 5433 não foi usado na execução documentada.
- A revisão `990fa9af113d` foi validada em PostgreSQL 17 descartável por `upgrade head`, `downgrade 8a62d13e4f90` e novo `upgrade head`, todos com código zero; essa revisão não foi aplicada aos bancos de desenvolvimento ou testes. A revisão `d8f4c2b19a70` foi validada no ambiente PostgreSQL de testes em etapa posterior. O estado atual do banco de desenvolvimento não foi consultado nesta atualização documental.


## Mensagens em canais de servidor

A revisão `b241de8f753a` sucede `a8c37d4e91b2`. Ela cria uma conversa interna do tipo CHANNEL por canal existente e mantém a publicação habilitada em canais de texto comuns. Criação de canais novos inicializa a conversa na mesma transação. O histórico usa mensagens, versões de edição e eventos existentes. O polling inclui criações, edições e exclusões com revisão monotônica por canal.

Em **Servidores → detalhes → Abrir canais**, o membro pode selecionar um canal acessível, consultar o histórico e denunciar mensagens de outros participantes. O proprietário pode configurar somente leitura. A exclusão de um canal com histórico o arquiva, preservando referências e evidências. Retenção automática e comunicação por áudio permanecem fora desta entrega.

Ver contratos, cursores e regras em `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md`. A aplicação da migration no banco de desenvolvimento depende de autorização.


## Autenticação em dois fatores

Validação desta entrega: suíte backend completa com 692 testes aprovados; suíte frontend com 207 testes aprovados em 13 arquivos (`npm test -- --maxWorkers=2`); build de produção aprovado. A migration foi exercitada em schema temporário do PostgreSQL isolado por upgrade, downgrade e novo upgrade.

A revisão `e21b7c84a603`, posterior a `b241de8f753a`, acrescenta configuração criptografada, desafios persistentes e auditoria. A seção Segurança e 2FA permite ativar TOTP, ver QR Code/chave manual, confirmar e guardar dez códigos de recuperação de uso único, regenerar e desativar com senha e segundo fator.

Variável obrigatória para configurar TOTP: `TWO_FACTOR_ENCRYPTION_KEY`, uma chave Fernet base64 de 32 bytes, independente de `JWT_SECRET_KEY`. Provisionar pelo gerenciador de segredos do ambiente. Para gerar localmente: executar `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` em terminal privado, transferir para a configuração e preservar uma cópia segura. Nenhuma chave real foi adicionada ao projeto. Não substituir a chave de uma instalação com usuários ativos: isso exige recriptografia controlada dos segredos. A versão atual permite regeneração do segredo por desativação e nova configuração, com prova forte.

Contratos:
- POST /users/login preserva a resposta de token em contas sem 2FA; em contas com 2FA retorna somente two_factor_required, challenge e expires_in.
- POST /users/login/2fa recebe challenge, code e recovery (booleano), consome o desafio e retorna o JWT normal.
- GET /users/me/2fa retorna somente enabled.
- POST /users/me/2fa/setup exige senha atual. Retorna QR SVG e chave manual somente na criação da configuração pendente, válida por dez minutos.
- POST /users/me/2fa/confirm exige senha e TOTP. Ativa e retorna dez recovery_codes e JWT renovado.
- POST /users/me/2fa/regenerate exige senha e TOTP ou recuperação. Invalida códigos e JWTs anteriores e retorna novo conjunto e JWT.
- POST /users/me/2fa/disable exige a mesma prova forte, remove segredo/códigos, invalida desafios e JWTs anteriores e retorna um JWT renovado.

O desafio aleatório dura cinco minutos, fica somente em memória no frontend e nunca serve como JWT. O banco guarda apenas seu hash. O lock por usuário serializa provas, consumo de recuperação e mudanças de configuração. Cinco provas inválidas bloqueiam novas tentativas por quinze minutos. TOTP aceita uma janela de 30 segundos anterior/posterior e impede reutilizar o mesmo passo temporal. Após ativar ou regenerar, aguardar o próximo código do autenticador ou usar uma recuperação para entrar novamente. Senhas e sanções continuam verificadas. A recuperação de senha não possui fluxo implementado e não contorna o segundo fator.

Para demonstrar em ambiente autorizado, provisionar a chave, aplicar a migration, acessar Segurança e 2FA, informar a senha e ler o QR em um autenticador. Confirmar o código, guardar as recuperações e sair. O próximo login exige o código da etapa temporal seguinte ou uma recuperação. Após usá-la, tentar novamente comprova uso único. A chave e os códigos não devem ser salvos em logs ou compartilhados.


## Pacote C — autodeclaração e servidores +18

Validação backend completa: 722 testes aprovados em 177,42 segundos no PostgreSQL isolado de testes, porta 55432. Frontend completo: 211 testes aprovados em 14 arquivos, em 60,97 segundos, com dois workers. O build de produção foi aprovado. A primeira execução completa apontou uma consulta adicional na listagem de membros; a regra etária passou a compartilhar a consulta existente e a asserção original de três consultas foi preservada.

O cadastro valida a idade mínima de 14 anos. A declaração legada é feita em POST /users/me/birth-date com senha; a data preenchida não pode ser editada nesta versão. GET /users/me continua restrito ao próprio usuário e os contratos públicos de busca não expõem nascimento.

ServerCreate recebe is_adult booleano estrito, que não pertence a ServerUpdate. A resposta de servidor expõe a classificação. A criação de servidor +18 requer adulto. Todos os routers de servidores usam uma dependência comum para negar acesso etário, além das autorizações existentes. A listagem exclui servidores +18 inacessíveis. O aceite de convite revalida a idade no serviço sob o lock do servidor, antes de consumir usos ou criar/reativar participação. Canais e mensagens revalidam idade pelo serviço de acesso. A transferência exige elegibilidade etária do destinatário. Evidências de canais +18 também são filtradas para equipe oficial menor ou sem data válida.

Os campos existentes birth_date e is_adult foram reutilizados. Esta entrega não cria migration. A autodeclaração não representa verificação documental nem altera is_verified.


## Pacote D — integração e preparação da demonstração

Em 24/11/2026 foram executados 724 testes backend (193,51 s), 212 testes frontend em 15 arquivos (69,95 s) e build de produção, todos aprovados. O backend usou exclusivamente plataforma_tcc_test em 127.0.0.1:55432. Foram incluídos um fluxo por HTTP loopback real combinando os Pacotes A/B/C e um ciclo completo das 20 migrations em schema temporário, com comparação de tabelas/colunas dos modelos. Isso não informa a revisão do banco de desenvolvimento, que não foi acessado.

Correção comprovada: renovação do JWT por ativação/regeneração/desativação de 2FA não atualizava o timer visual da sessão. tokenStorage agora emite uma notificação sem dados sensíveis ao substituir um token e AuthProvider reagenda a expiração. O teste específico preserva a sessão até a expiração renovada.

O ensaio no Chrome local validou frontend real → API temporária → PostgreSQL isolado para login sem 2FA, listagem/detalhes de servidores, histórico de canal +18, envio, persistência após recarga, seleção de outro canal sem conteúdo anterior e logout. Contas e mensagens eram fictícias em schema exclusivo de ensaio. O worker permaneceu desligado, sem chamadas OpenAI.

Configuração local: TWO_FACTOR_ENCRYPTION_KEY ausente; requer provisionamento pelo operador antes de ativação real. A chave OpenAI foi detectada no arquivo local, mas o worker lê OPENAI_API_KEY do ambiente do processo. A flag de worker está habilitada no arquivo; os processos isolados usaram configuração desligada. Nenhuma credencial foi registrada neste relatório.

Estado geral PARCIAL para demonstração completa: os fluxos automatizados passaram e houve ensaio de navegação real, mas faltam autenticador físico, login 2FA pela interface, polling simultâneo em dois navegadores e ensaio completo de moderação oficial. Ver docs/roteiro-demonstracao.md. Nenhuma migration nova foi criada neste pacote.
