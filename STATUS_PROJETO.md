# Status do projeto

**Última atualização do status:** 13/11/2026.

**Última execução dos testes documentada:** testes de autorização: `34 passed`; suíte completa: `125 passed, 0 failed`, no PostgreSQL isolado de testes `plataforma_tcc_test` (`127.0.0.1:55432`).
**Última consulta ao estado Alembic do banco de desenvolvimento documentada:** 10/11/2026 (`bc365585aa97`, então head). A revisão `8a62d13e4f90` foi criada depois; o estado atual do banco de desenvolvimento não foi verificado nesta atualização documental.
Este documento descreve o estado verificado nessa análise e deve ser atualizado após mudanças futuras.

## Resumo

O repositório contém uma API FastAPI com cadastro/login JWT, modelos SQLAlchemy para usuários, relacionamentos, servidores, conversas e mensagens, e migrações Alembic. Existem endpoints para usuários, CRUD básico e configuração de permissões de `@everyone` nos servidores, núcleo de participação, leitura de cargos, criação/listagem de conversas e envio/listagem de mensagens. O serviço central resolve grants, calcula níveis hierárquicos e compara ator e alvo como requisito hierárquico separado das permissões funcionais. A última suíte documentada teve 125 testes aprovados. Não foi encontrado frontend.

## Arquitetura observada

- **API:** `app/main.py`, FastAPI, versão declarada `0.3.0`.
- **Configuração e DB:** `app/settings.py`, `app/database.py`; SQLAlchemy com `postgresql+psycopg`, `pool_pre_ping` e sessões síncronas.
- **Autenticação:** `app/auth.py`; Bearer JWT HS256, usuário identificado pelo `sub`, conta deve existir e estar ativa.
- **Validação:** `app/schemas.py`, Pydantic v2.
- **Domínio:** `app/models/` possui 17 modelos/tabelas. As chaves estrangeiras existem, mas não há declarações ORM `relationship()`.
- **Rotas:** `app/routers/users.py`, `conversations.py`, `messages.py`, `servers.py`, `server_members.py` e `server_roles.py`.
- **Serviços:** `app/services/conversation_service.py`, `message_service.py`, `server_service.py`, `server_member_service.py`, `server_role_service.py` e `server_authorization_service.py`; `app/server_permissions.py` define o catálogo de permissões reconhecidas.
- **Especificação de autorização de servidores:** [ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md](ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md) registra regras aprovadas e pontos pendentes; é documentação de comportamento futuro, não implementação.
- **Banco local:** Docker Compose define PostgreSQL 17, volume persistente, healthcheck e publicação `5433:5432`. Não define serviço da API nem Dockerfile.
- **Banco de testes:** `docker-compose.test.yml` define PostgreSQL 17 isolado, com container e volume próprios e porta `55432`; os testes usam `plataforma_tcc_test`.
- **Testes:** `pytest.ini`, `requirements-test.txt` e `tests/`; o `conftest.py` valida host local, porta, usuário e nome exato do banco de testes, substitui a dependência de banco da API e usa segredo JWT sintético. A fixture cria e remove as tabelas no banco de testes via metadata e reverte os dados de cada caso; não executa Alembic.
- **Etapa 2 de servidores:** as decisões de negócio para membros, expulsões, banimentos, convites, auditoria e transferência estão documentadas em `CONTEXTO_TCC.md` e `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md`; não significam que esses fluxos estejam implementados.
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
| `POST /servers/` | Cria servidor e participação ativa do proprietário na mesma transação | Bearer JWT |
| `GET /servers/` | Lista servidores com participação `ACTIVE` do usuário | Bearer JWT |
| `GET /servers/{server_id}` | Consulta servidor somente com participação ativa | Bearer JWT |
| `PATCH /servers/{server_id}` | Proprietário atualiza nome e descrição; campos de configuração e `owner_id` não são aceitos | Bearer JWT |
| `PATCH /servers/{server_id}/everyone-permissions` | Proprietário ativo substitui toda a configuração; registra valores anterior/novo em `ServerConfigHistory` atomicamente | Bearer JWT |
| `GET /servers/{server_id}/members` | Lista membros `ACTIVE`, paginados, com dados mínimos | Bearer JWT e participação ativa do solicitante |
| `GET /servers/{server_id}/members/{user_id}` | Consulta um membro `ACTIVE` do servidor | Bearer JWT e participação ativa do solicitante |
| `POST /servers/{server_id}/leave` | Encerra a participação do usuário autenticado e limpa cargos individuais na mesma transação | Bearer JWT e participação ativa |
| `GET /servers/{server_id}/roles` | Lista cargos do servidor em ordem crescente de `position`, com `id` como desempate | Bearer JWT e participação ativa; não exige `manage_roles` |
| `GET /servers/{server_id}/roles/{role_id}` | Consulta cargo que pertence ao servidor da rota | Bearer JWT e participação ativa; não exige `manage_roles` |

## Modelos existentes

### Usuários e relacionamentos

`User`, `UserPrivacySettings`, `Friendship`, `Block`, `PlatformStaff`.

### Servidores

`Server`, `ServerMember`, `ServerRole`, `ServerMemberRole`, `ServerChannel`, `ServerInvite`, `ServerConfigHistory`.

`Server` possui `everyone_permissions` JSONB `NOT NULL`, default `{}` e constraint `ck_servers_everyone_permissions_object`. `ServerRole.is_system_role` também está presente, independente de `is_default`; ambos foram introduzidos pela revisão Alembic `8a62d13e4f90`, descendente de `bc365585aa97`. `is_default` e seu índice parcial permanecem sem função de negócio aprovada e não representam `@everyone` nem cargos reservados. A existência desses campos no modelo e na migration não confirma que a revisão foi aplicada ao banco de desenvolvimento.

`ServerRole.position` é inteiro não nulo, sem default Python ou de banco. O modelo inclui `ck_server_roles_position_positive` (`position >= 1`); posições repetidas são permitidas. A migration `990fa9af113d`, descendente de `8a62d13e4f90`, foi validada com upgrade e downgrade em PostgreSQL descartável. Nenhuma migration foi aplicada aos bancos de desenvolvimento ou testes.

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
- Resolução central de permissões: união dos grants booleanos de `everyone_permissions` e dos cargos individuais do membro `ACTIVE`; somente as seis chaves documentadas são reconhecidas. Proprietário é identificado separadamente; hierarquia e autorização de canais privados não são resolvidas por esse serviço.
- Configuração de `@everyone`: `PATCH /servers/{server_id}/everyone-permissions` exige proprietário real com participação `ACTIVE`, substitui o objeto completo, aceita somente as seis permissões documentadas com valores booleanos estritos, rejeita chaves desconhecidas e aceita `{}`. Configuração e histórico de `ServerConfigHistory` são gravados na mesma transação; falha no histórico reverte a alteração. `manage_roles` não concede essa autoridade e `@everyone` não concede acesso a canais privados.
- Leitura de cargos: os endpoints `GET /servers/{server_id}/roles` e `GET /servers/{server_id}/roles/{role_id}` exigem JWT e participação `ACTIVE`, permitem acesso ao proprietário e a qualquer membro ativo sem `manage_roles`, e limitam resultados ao servidor informado. A consulta individual verifica `role_id` e `server_id`; a listagem ordena por `position` crescente e `id` como desempate. Os campos `is_default` e `is_system_role` são retornados independentemente, sem atribuição de nova semântica.
- Hierarquia: `get_member_hierarchy_level(db, server_id, user_id)` calcula o maior nível de cargos individuais para membro `ACTIVE`, ignorando `@everyone`; sem cargos retorna 0. `is_hierarchy_comparison_approved(db, server_id, actor_user_id, target_user_id)`, ambas em `app/services/server_authorization_service.py`, valida ator e alvo `ACTIVE` no mesmo servidor (ausentes/LEFT resultam em 404). Proprietário passa sobre membro ativo independente da posição; membro comum precisa de posição estritamente superior e não pode agir sobre proprietário; autoação, igualdade ou nível inferior retorna `False`. A função não substitui a permissão específica e exige que o ID do ator venha do principal autenticado. A autoridade especial do proprietário permanece separada em `ResolvedServerPermissions.is_owner`. Integrações com gerenciamento de cargos e kick/ban/unban continuam pendentes.

## Implementação parcial: modelos presentes, API incompleta

- **Amizades e bloqueios:** tabelas e constraints existem. Não há endpoints para gerenciar amizade/bloqueio. Bloqueios são consultados ao iniciar/reusar conversa direta, enviar mensagens e ler o histórico; um bloqueio em qualquer direção impede as três operações sem apagar mensagens. Amizades aceitas e privacidade do destinatário são verificadas antes de reativar uma participação `LEFT`.
- **Privacidade:** preferências e defaults existem; não há API para lê-las ou atualizá-las. `allow_friend_requests`, `show_online_status` e `allow_group_invites` não são aplicados em rotas existentes.
- **Grupos:** tabelas de conversa, participante e convite existem; não há endpoint de criação ou gestão de grupos, participantes, papéis ou convites.
- **Servidores e participação:** CRUD básico, listagem/consulta de membros ativos, saída voluntária, leitura de cargos, resolvedor central de grants e configuração de `everyone_permissions` estão implementados. A saída protege o proprietário, rejeita repetição, remove atribuições individuais e atualiza participação/`left_at` atomicamente. O cálculo do nível e a comparação hierárquica central estão implementados, mas ainda não estão integrados às operações. Criação, edição, exclusão e atribuição/remoção de cargos e limites contra escalada ainda não estão implementados; a existência do resolvedor não equivale a essas operações. Também não há operação de expulsão, banimentos, convites, auditoria de moderação, transferência de propriedade, canais privados ou mensagens de servidor. As decisões aprovadas e pendências estão em [ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md](ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md).
- **Mensagens/exclusões:** envio e leitura estão disponíveis; existe tabela/campos para exclusão e timestamp de edição, mas não há endpoints/serviços para editar ou excluir, nem histórico de edição.
- **Verificação de conta:** `is_verified` existe no modelo/resposta, mas não há fluxo para verificar conta. Novos usuários não recebem verificação por este endpoint.

## Pendências de produto

- Continuar o módulo de servidores conforme [ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md](ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md): gestão de cargos (criação, edição, exclusão, atribuições e integração das regras hierárquicas), expulsões/banimentos, canais privados, convites, transferência/auditoria e mensagens de servidor. CRUD, núcleo de participação, leitura de cargos, resolução central de grants, configuração de `@everyone` e comparação hierárquica isolada estão disponíveis.
- Gestão completa de grupos, incluindo convites e transferência de administração.
- Edição e exclusão de mensagens com regras de autoria, permissões, janela de 15 minutos e histórico.
- APIs para amizades, bloqueios e configurações de privacidade.
- APIs/operações de gestão de cargos, atribuições, integração da comparação hierárquica com operações, permissões individuais, canais privados e convites, além das operações de servidor e membros ainda não implementadas. O cálculo do nível, a comparação hierárquica isolada, a leitura de cargos, a resolução de grants e a configuração de `everyone_permissions` já estão implementados.
- Denúncias, moderação humana/assistida por IA, histórico de penalidades e pontuação de segurança.
- Verificação de idade e acesso a espaços +18; autenticação em dois fatores.
- Upload/armazenamento de arquivos fora do PostgreSQL e funcionalidades de mídia.
- Voz em tempo real e WebRTC.
- Notificações, menções, busca, verificação de links e recursos planejados em [CONTEXTO_TCC.md](CONTEXTO_TCC.md).
- Frontend React/TypeScript/Vite/Tailwind.
- Ampliar a cobertura automatizada para as operações de servidores ainda pendentes; leitura de cargos possui testes de integração.

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

## Especificação aprovada e estado de implementação

- As decisões da Etapa 2 estão consolidadas em `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md` e resumidas em `CONTEXTO_TCC.md`; requisitos não significam implementação. Saída, expulsão e banimento são distintos; saída/expulsão encerram participação como `LEFT`, limpam cargos e não banem; expulsão permite retorno por convite, enquanto banimento ativo impede entrada até revogação. Estão aprovadas as permissões independentes `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles`, além de `mention_everyone` para menções, a hierarquia estrita, posições de cargo a partir de 1 e as exceções do proprietário. Membros comuns com `manage_roles` precisam respeitar hierarquia do cargo/alvo e só podem conceder permissões que já possuem efetivamente; JSONB e atribuições não podem contornar esse limite. O campo `ServerRole.is_system_role` e `Server.everyone_permissions` já existem no modelo e na revisão `8a62d13e4f90`; o endpoint owner-only de `everyone_permissions` e o resolvedor central também estão implementados. A classificação exata dos cargos reservados continua pendente. Todos os membros `ACTIVE` podem visualizar cargos, sem autoridade de mutação; cargo atribuído não pode ser excluído e retorna `409`. Cada ciclo de banimento guarda `target_highest_role_position`. `@everyone` não concede acesso a canais privados; esse acesso depende de cargo individual autorizado e o proprietário mantém acesso especial. `ServerBans` e `ServerAuditLogs` continuam estruturas conceituais, ainda não implementadas.
- Além do CRUD básico e do núcleo de participação, estão implementados a leitura de cargos, o resolvedor central, a configuração owner-only de `everyone_permissions`, o cálculo de nível e a comparação hierárquica centralizada. Permanecem pendentes a integração dessa comparação com gerenciamento de cargos e kick/ban/unban, as regras operacionais de autoridade e a criação, edição, exclusão e atribuição/remoção de cargos, além de expulsões, banimentos, convites, auditoria de moderação, transferência, canais privados e mensagens de servidor.
- Permanecem pendentes decisões de produto fora do conjunto consolidado: catálogo de permissões além das aprovadas, finalidade de `is_default`, identificação exata dos cargos reservados ao sistema e seu mapeamento nos registros existentes antes da migration, representação persistente de acesso privado por cargo, detalhamento dos limites para permissões funcionais em JSONB além do teto de concessão já aprovado, política HTTP para recursos privados, eventos adicionais de auditoria além dos já aprovados, política de ciclo de vida de servidor/canal e detalhes da verificação de idade. Já está decidido que somente o proprietário altera `Server.everyone_permissions` e configura cargos autorizados por canal privado; `manage_roles` não concede essas autoridades. Acesso privado por `@everyone` não está pendente: foi decidido que ele não concede acesso.
- A análise estática encontrou `is_default` apenas no modelo e na migration, sem uso em schemas, rotas, serviços ou testes. O preflight autorizado de leitura encontrou zero registros com `is_default=true` e zero posições inválidas. A migration de posição foi validada apenas no PostgreSQL descartável; nenhuma migration foi aplicada aos bancos de desenvolvimento ou testes nesta etapa.
- Os sete modelos/tabelas existentes continuam sendo a base de dados. Há testes para o CRUD básico e testes de integração para leitura de cargos; ainda não há implementação de mutações/autorização hierárquica de cargos, canais, convites ou mensagens de servidores.

### Diferenças entre decisões e modelos atuais

- `Server.everyone_permissions` JSONB e a constraint de objeto estão no modelo e na revisão Alembic `8a62d13e4f90`; a rota de substituição integral, validação estrita, autorização owner-only e gravação transacional em `ServerConfigHistory` estão implementadas. A revisão no banco de desenvolvimento não foi verificada nesta atualização.
- `ServerChannel` não armazena visibilidade nem cargos autorizados; a concessão de acesso privado por cargo ainda não tem representação persistente no modelo.
- A decisão de autorização está definida, mas não implementada: somente o proprietário configurará cargos autorizados em canais privados; concessões e remoções precisarão de auditoria transacional. `manage_roles` não concederá essa autoridade, e `@everyone` continuará sem acesso privado.
- `ServerMemberRole` permite associações entre membros e cargos; a saída voluntária implementada remove atribuições atomicamente. A API ainda não permite atribuir/remover cargos nem calcula hierarquia ou autorização de cargos.
- `ServerMember` permite representar participação `ACTIVE`/`LEFT`, `left_at` e a unicidade `(server_id, user_id)`. A listagem e consulta de membros ativos e a saída voluntária estão implementadas; expulsão e reentrada por convite não estão.
- O serviço central calcula a união de grants documentados de `everyone_permissions` e cargos individuais para membros ativos. CRUD/atribuição de cargos, autorização hierárquica e limites contra escalada ainda não estão implementados.
- Os limites aprovados para concessão de permissões (`manage_roles`, permissão efetiva do ator, delta de grants e validação dos alvos) ainda não têm implementação ou testes; alteração de JSONB não pode ser tratada apenas como validação de posição.
- `ServerRole.is_default` é um booleano não nulo com default Python `False`; o índice único parcial `uq_server_roles_one_default` permite no máximo um cargo marcado por servidor. Não há lógica de API que o consulte. A migration original não define default no banco. `@everyone` é uma configuração distinta em `Server.everyone_permissions`; não se deve associá-lo a `is_default`. `ServerRole.is_system_role` é um campo independente já presente no modelo e na revisão `8a62d13e4f90`; a classificação exata dos cargos e a operação de proteção ainda estão pendentes.
- `ServerRole.position` é inteiro não nulo sem default Python ou de banco; o modelo e a revisão `990fa9af113d` impõem `position >= 1` com `ck_server_roles_position_positive`. Posições iguais são permitidas. A migração foi validada em PostgreSQL descartável com upgrade/downgrade. O cálculo e a comparação hierárquica centralizada estão implementados; sua integração com operações permanece pendente.
- Não existem `ServerBans` ou `ServerAuditLogs`, nem fluxos de expulsão, banimento/revogação, consulta de moderação, convites ou transferência. Os campos, snapshot de hierarquia e tipos de evento estão definidos conceitualmente, mas as estruturas e regras de persistência ainda não foram implementadas.
- Esses pontos são lacunas de implementação/modelagem. A etapa de CRUD básico usou o schema existente e não criou migration.

## Migrações e banco observado

A cadeia de revisões Alembic presente no repositório contém oito arquivos:

1. `f46a25e64a14`: tabela de usuários.
2. `b3a25b568222`: data de nascimento de usuários.
3. `1b2711d27349`: privacidade, amizades, bloqueios e staff.
4. `457fe8255da3`: servidores, membros, cargos, canais, convites e histórico.
5. `cd34f0c32d15`: conversas, participantes e convites.
6. `bc365585aa97`: mensagens e exclusões individuais.
7. `8a62d13e4f90`: adiciona `ServerRole.is_system_role`, `Server.everyone_permissions` JSONB e `ck_servers_everyone_permissions_object`; sua revisão anterior é `bc365585aa97`.
8. `990fa9af113d`: adiciona `ck_server_roles_position_positive` (`position >= 1`); sua revisão anterior é `8a62d13e4f90`.

Consulta somente leitura ao banco de desenvolvimento realizada em 10/11/2026 indicou `bc365585aa97 (head)`, antes da criação da revisão `8a62d13e4f90`. Isso é um registro histórico, não uma confirmação do estado atual do banco. Esta atualização documental não consultou banco nem executou migration; portanto, o estado atual do banco de desenvolvimento permanece não verificado.

## Verificação desta análise

- Testes de autorização após a implementação da comparação hierárquica: **34 passed**. Última execução da suíte completa: **125 passed, 0 failed**, exclusivamente em `plataforma_tcc_test` (`127.0.0.1:55432`). Esta atualização documental não executou testes.
- A URL de testes é validada pelo `tests/conftest.py` para `plataforma_tcc_test`, host local, porta 55432 e usuário `tcc_test`; o banco de desenvolvimento na porta 5433 não foi usado na execução documentada.
- A revisão `990fa9af113d` foi validada em PostgreSQL 17 descartável por `upgrade head`, `downgrade 8a62d13e4f90` e novo `upgrade head`, todos com código zero. Nenhuma migration foi aplicada aos bancos de desenvolvimento ou testes. O estado atual do banco de desenvolvimento não foi consultado.
