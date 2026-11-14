# Planejamento técnico da Etapa 2 — Membros, cargos, convites e auditoria

**Estado:** planejamento parcialmente executado. A leitura de cargos, o resolvedor de grants, a configuração de `everyone_permissions`, a validação estrutural de `ServerRole.position`, o cálculo do nível hierárquico e a comparação centralizada entre ator e alvo estão implementados. A integração dessas verificações com regras de autoridade e operações de cargos permanece pendente.

**Base da análise:** código, migrations, testes e documentos de referência examinados em 12/11/2026. Não houve consulta a bancos de dados nesta tarefa.

## 1. Objetivo e limites

Planejar, em blocos pequenos, a implementação de gerenciamento de membros, cargos, permissões, canais privados, convites, expulsões, banimentos, auditoria e transferência de propriedade. O escopo mantém mensagens dos canais de servidor como etapa separada; o modelo atual `Message` é ligado a `Conversation`.

Este documento consolida decisões existentes. Ele não altera `CONTEXTO_TCC.md`, `STATUS_PROJETO.md` ou `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md`. A implementação deverá respeitar essas referências, os controles de autorização no backend, as transações e as constraints do PostgreSQL.

## 2. Diagnóstico do estado atual

### Arquitetura observada

- FastAPI síncrono, SQLAlchemy síncrono, PostgreSQL via Psycopg e schemas Pydantic.
- `app/auth.py` valida Bearer JWT e carrega usuário existente e ativo.
- `app/database.py` oferece `Session` por dependência; serviços atuais gerenciam commit/rollback explicitamente.
- `app/routers/servers.py` expõe somente CRUD básico; `app/services/server_service.py` contém sua lógica.
- Modelos de domínio são registrados em `app/models/__init__.py`. As relações são definidas por FKs e consultas explícitas; os modelos não usam `relationship()`.
- A migration `457fe8255da3` cria as tabelas atuais de servidores. A cadeia atual do código termina em `990fa9af113d`, descendente de `8a62d13e4f90`; a existência da revisão no código não implica que tenha sido aplicada aos bancos de desenvolvimento ou testes.
- A infraestrutura de integração usa o PostgreSQL dedicado `plataforma_tcc_test`, porta 55432, protegido por validações em `tests/conftest.py`. A fixture de testes cria e remove tabelas nesse banco, sem Alembic.

### Disponibilidade efetiva

Estão implementados `POST /servers/`, `GET /servers/`, `GET /servers/{server_id}` e `PATCH /servers/{server_id}`, além de `GET /servers/{server_id}/members`, `GET /servers/{server_id}/members/{user_id}` e `POST /servers/{server_id}/leave`. A criação associa atomicamente o proprietário autenticado como membro ativo; consulta/listagem de servidores e membros exigem participação ativa; a atualização básica é exclusiva do proprietário; a saída remove cargos individuais e encerra a participação atomicamente. A leitura de cargos também está implementada em `GET /servers/{server_id}/roles` e `GET /servers/{server_id}/roles/{role_id}`; exige JWT e participação `ACTIVE`, permite qualquer membro ativo sem `manage_roles`, limita o cargo individual ao servidor da URL e ordena a lista por `position` crescente, com ID como desempate.

O núcleo de participação está implementado e coberto por testes. Também estão implementados no código as migrations `8a62d13e4f90` (com `Server.everyone_permissions`, sua constraint de objeto JSON e `ServerRole.is_system_role`) e `990fa9af113d` (constraint de posição), o serviço de resolução da união dos grants de `@everyone` e dos cargos individuais, `PATCH /servers/{server_id}/everyone-permissions` e os endpoints de leitura de cargos. A configuração de `@everyone` é exclusiva do proprietário ativo e tem histórico transacional em `ServerConfigHistory`; a leitura de cargos exige participação ativa e não exige `manage_roles`. A última execução da suíte completa foi `102 passed, 0 failed`, incluindo 7 testes específicos de posição; isso não representa cobertura das mutações de cargos. A existência das migrations no repositório não confirma por si só que foram aplicadas a qualquer banco.

Ainda não existem operações de mutação de cargos, atribuições ou hierarquia operacional, convites, banimentos, auditoria de moderação, canais privados ou transferência. `ServerInvite` é somente modelo e `ServerChannel` ainda não representa política de privacidade. `ServerBans` e `ServerAuditLogs` não existem como modelos.

### Modelos e garantias que podem ser reutilizados

| Entidade | Estrutura encontrada | O que já garante / lacuna |
|---|---|---|
| `Server` | `owner_id`, dados básicos, flags, `everyone_permissions` e timestamps | FK para usuário; `everyone_permissions` é JSONB não nulo, default `{}` no ORM/banco e constraint exige objeto JSON. O endpoint atual permite que somente o proprietário ativo faça substituição integral e grava o histórico atomicamente. |
| `ServerMember` | `server_id`, `user_id`, `status`, `joined_at`, `left_at` | Unicidade `(server_id,user_id)`, status `ACTIVE`/`LEFT` e consistência de `left_at`; suficiente para reentrada na mesma linha. Não implementa transições nem bloqueio de banimento. |
| `ServerRole` | nome, descrição, `permissions` JSONB, `position`, `is_default`, `is_system_role`, `created_at` | Nome único por servidor; no máximo um `is_default=true` por servidor via índice parcial. `is_system_role` existe, é independente de `is_default` e tem default `false`. `position` é inteiro não nulo sem default Python ou de banco e a constraint `ck_server_roles_position_positive` exige valor >= 1; posições iguais são permitidas. O cálculo usa a maior posição dos cargos individuais; a comparação estrita entre ator/alvo está centralizada no serviço e sua integração com operações ainda está pendente. A lista/mapeamento dos cargos reservados continua pendente; nenhum cargo deve ser marcado por inferência. |
| `ServerMemberRole` | membro, cargo, servidor, atribuidor e data | Unicidade de membro/cargo e FKs compostas que impedem associações entre servidores diferentes. Não remove atribuições automaticamente nem guarda histórico de remoções. |
| `ServerChannel` | nome, descrição, tipo, posição e servidor | Não representa visibilidade privada nem cargos autorizados. |
| `ServerInvite` | criador, servidor, hash de token, expiração, limite/contador de uso, revogação | Hash único e checks para expiração/contagem. Sem fluxo de emissão, validação, consumo ou revogação. |
| `ServerConfigHistory` | servidor, ator, configuração, valor anterior/novo e timestamp | Já registra a alteração de `everyone_permissions`; reutilizável para alteração de `owner_id` na futura transferência. |

Nenhuma funcionalidade de mutação de cargos/permissões deve ser declarada concluída a partir da existência dos modelos. A leitura de cargos, o resolvedor central de grants, a configuração de `@everyone`, o núcleo de participação, o cálculo de nível e a comparação hierárquica centralizada estão implementados; integração com mutações/ações administrativas, mutações e atribuições seguem pendentes.

## 3. Decisões de negócio consolidadas

### Membros, saída, expulsão e reentrada

- Somente participação `ACTIVE` concede acesso e permissões.
- Saída voluntária encerra participação como `LEFT`, preenche `left_at`, remove atribuições individuais e não cria banimento. O proprietário precisa transferir a propriedade antes de sair.
- Expulsão é distinta de banimento: encerra participação como `LEFT`, registra `left_at`, apaga cargos e gera `MEMBER_KICKED`; não impede futura entrada por convite.
- Repetir saída/expulsão de participação `LEFT` retorna erro; não é idempotente.
- Banimento ativo impede entrada mesmo com convite válido. Revogação manual apenas permite nova tentativa; não reativa participação automaticamente.
- Reentrada por convite reutiliza `(server_id,user_id)`, atualiza `joined_at`, limpa `left_at`, não restaura cargos e exige ausência de banimento ativo.
- O proprietário não pode ser expulso/banido e não pode sair enquanto proprietário. A transferência é para qualquer membro `ACTIVE` e não banido, sem requisito de cargo.

### Permissões independentes

O catálogo aprovado para esta etapa contém:

| Permissão | Finalidade estabelecida | Exceção do proprietário |
|---|---|---|
| `kick_members` | Expulsar membro ativo, respeitada a hierarquia | Pode expulsar outro membro ativo sem essa permissão ou comparação hierárquica; não pode expulsar a si nem o proprietário |
| `ban_members` | Banir membro ativo, respeitada a hierarquia | Pode banir outro membro ativo sem essa permissão ou comparação hierárquica; não pode banir a si nem o proprietário |
| `unban_members` | Revogar banimento ativo, comparando com o snapshot hierárquico | Pode revogar qualquer banimento |
| `manage_invites` | Criar/revogar convites | Pode criar/revogar sem a permissão |
| `manage_roles` | Gerenciar cargos, sujeito à hierarquia e às regras desta seção | Pode gerenciar cargos comuns; não pode alterar/excluir cargos `is_system_role` |

São capacidades independentes. Nenhuma é concedida por uma permissão administrativa genérica nem implica outra. O JSONB representa concessões booleanas: valor `true` concede, ausência não concede, e `false` em outro cargo não anula concessão. A união vale entre permissões gerais de `@everyone` e cargos individuais ativos; hierarquia continua sendo calculada separadamente. Uma concessão explícita em `everyone_permissions` deve ser distinguida de concessão implícita: a implementação deve validar a chave e seu valor, sem inferir permissões administrativas.

Outras permissões de canais/mensagens não devem ser inventadas. `mention_everyone` aparece na especificação do produto, mas o fluxo de mensagens de servidor e seu catálogo operacional estão fora deste bloco.

### Hierarquia e gestão de cargos

- Maior `position` dentre os cargos individuais determina a hierarquia do membro.
- Membro sem cargos individuais tem nível 0; cargos individuais precisam ter posição `>= 1`; `@everyone` não integra o cálculo.
- Cargo com posição maior tem hierarquia superior. Ações comparativas exigem superioridade estrita.
- Membro não proprietário que gerencia cargo precisa de `manage_roles` e só pode modificar cargo com posição abaixo de sua maior posição individual. Não pode modificar cargo em posição igual/superior nem promover a si ou outro acima da própria autoridade.
- Ao alterar atribuições de outro membro, o ator precisa também estar acima do alvo; igualdade não basta.
- Cargos reservados são identificados por `ServerRole.is_system_role`, campo próprio separado de `is_default`; essa marca não depende de nome ou posição. Cargos marcados não podem ser excluídos nem ter propriedades estruturais modificadas por nenhum ator, inclusive o proprietário. O proprietário mantém autoridade especial sobre os demais cargos comuns.
- Todos os membros `ACTIVE` podem visualizar cargos; a consulta exige autenticação/participação e não autoriza mutações. Membros `LEFT` não podem consultar.
- Excluir cargo com atribuições individuais retorna `409 Conflict`; não remover associações automaticamente nem alterar implicitamente permissões efetivas.
- O proprietário pode configurar todas as permissões aprovadas em cargos comuns; não pode modificar cargos `is_system_role`. Membro comum com `manage_roles` só pode conceder permissões que já possui efetivamente; não pode conceder `manage_roles` acima da própria autoridade.
- Em edição de JSONB, identificar delta de concessões antes/depois. Cada nova permissão efetiva concedida a um cargo ou a um alvo deve pertencer ao conjunto efetivo do ator; permissões removidas não são concessões, mas a operação continua sujeita a `manage_roles`, posição, hierarquia do alvo e proteção de cargo reservado.
- Ao editar cargo que já possui membros ativos, verificar a hierarquia de todos os alvos afetados e as permissões efetivas antes/depois. Ao atribuir cargo, comparar o conjunto efetivo do membro-alvo antes/depois; a atribuição não pode conferir permissões que o ator não possui. Para atribuição ao próprio ator, o mesmo limite impede autopromoção funcional.
- A exceção do proprietário não depende de suas permissões de cargo. Nenhuma chave nova é criada por esta regra; validação usa o catálogo aprovado.

### `@everyone` e canais privados

`@everyone` é papel implícito do servidor, sem linha em `server_member_roles`, e suas permissões gerais residem em `Server.everyone_permissions` (JSONB). **Ele não concede acesso a canal privado.** Para acessar canal privado, o membro ativo deve possuir pelo menos um cargo individual explicitamente autorizado para aquele canal. A união funcional das permissões dos cargos continua válida. O proprietário sempre acessa canais privados do seu servidor. Permissões gerais de `@everyone` nunca substituem as regras particulares de acesso do canal.

Somente o proprietário pode alterar `Server.everyone_permissions`; `manage_roles` não concede essa autoridade. O serviço valida o JSONB e o catálogo aprovado no backend, grava valores anterior/novo em `ServerConfigHistory` e atualiza a configuração na mesma transação. Após o commit, os grants gerais passam a valer imediatamente para todos os membros ativos, em união com os cargos individuais. A alteração não modifica acesso a canais privados.

Somente o proprietário pode configurar quais cargos individuais autorizam acesso a cada canal privado. `manage_roles` não concede essa autoridade. Cada concessão ou remoção é validada no backend, gravada em `ServerAuditLogs` e confirmada atomicamente com a associação. `@everyone` não pode ser configurado como autorização; o proprietário mantém acesso especial mesmo sem cargo associado.

### `ServerRole.is_default` e `is_system_role`

Decisão atual: preservar temporariamente a coluna `is_default` e seu índice; não associar a `@everyone`, não atribuir finalidade de negócio e não remover nesta etapa. A identificação de cargos reservados foi aprovada por campo independente `is_system_role`, já presente no modelo e na migration `8a62d13e4f90`. A lista exata dos cargos e o mapeamento dos registros para eventual marcação continuam pendentes; nenhum cargo é presumido como reservado. Quando marcada, a proteção definida impede alteração estrutural e exclusão inclusive pelo proprietário.

## 4. Modelagem proposta

Nomes de estruturas novos são conceituais; seguir convenções físicas existentes durante a implementação.

### 4.1 Alterações e estruturas reutilizadas

**`Server`:** `everyone_permissions JSONB NOT NULL DEFAULT '{}'` já existe no modelo e na revisão `8a62d13e4f90`, com validação de objeto. A configuração é carregada separadamente da autorização de canais privados. Não há necessidade identificada de GIN para a leitura usual por linha do servidor.

**`ServerRole`:** `is_system_role BOOLEAN NOT NULL DEFAULT false` já existe no modelo e na revisão `8a62d13e4f90`, independente de `is_default`. `position` não tem default Python nem de banco; o modelo e a revisão `990fa9af113d` impõem `CHECK (position >= 1)` com `ck_server_roles_position_positive`, sem impedir posições repetidas. O preflight autorizado encontrou zero servidores, cargos, atribuições, posições inválidas e cargos com `is_default=true`; não houve backfill. A migration foi validada em PostgreSQL descartável e não foi aplicada aos bancos de desenvolvimento ou testes. Não atribuir `is_system_role=true` por nome, posição ou `is_default`; preservar `is_default` e seu índice sem associá-lo a `@everyone` ou a cargo reservado.

**`ServerMember` e `ServerMemberRole`:** manter esquema existente. Serviços fazem transições de status e remoção de associações na mesma transação. A reentrada não cria linha ou atribuição histórica nova automaticamente.

**`ServerInvite`:** reutilizar tabela e constraints atuais. Um índice composto adicional só deve ser criado se os endpoints de listagem/perfil de consultas o justificarem; o hash único e os checks já existem.

**`ServerConfigHistory`:** já é reutilizado pelo endpoint de `everyone_permissions`; deverá também apoiar a transferência de propriedade, registrando `owner_id` anterior/novo junto da atualização e do evento de auditoria.

### 4.2 Representação de cargos especiais reservados

O campo próprio aprovado é `ServerRole.is_system_role`, booleano não nulo com default falso, independente de `is_default`, já incluído na revisão `8a62d13e4f90`. O backend deverá controlar o campo; payloads da API não podem defini-lo nem alterá-lo. A lista de cargos reservados e o mapeamento dos registros existentes ainda dependem de aprovação; não inferir por nome, posição ou `is_default`, nem marcar qualquer cargo nesta etapa de planejamento. Cargos marcados não podem ser excluídos nem ter propriedades estruturais modificadas, inclusive pelo proprietário.

### 4.3 `ServerChannel` e cargos autorizados

O modelo atual não contém campo de privacidade nem associação de cargos autorizados. Proposta mínima:

1. Adicionar a `ServerChannel` um indicador `is_private` não nulo com default falso. O servidor é identificado na própria linha.
2. Criar tabela de associação conceitual `ServerChannelRole` com `server_id`, `channel_id` e `role_id`, PK composta ou unique de `(channel_id,role_id)`, timestamps opcionais apenas se aprovados tecnicamente.
3. Criar `UNIQUE(id, server_id)` em `ServerChannel` para permitir FK composta `(channel_id,server_id)` e FK composta `(role_id,server_id)` para `ServerRole(id,server_id)`. Isso impede associar cargo de outro servidor.
4. Indexar associação pelo canal para autorizar leitura; avaliar índice reverso por `(server_id,role_id)` somente se queries de canais do membro o exigirem.
5. Não criar associação para `@everyone` nem por usuário. A query de acesso exige membro ativo e interseção entre seus cargos individuais e a associação do canal. Verificar essa interseção antes de buscar/serializar dados; o proprietário do servidor tem bypass explícito.

FKs de associação não devem apagar histórico de auditoria em cascata. Exclusão de canal/servidor segue pendente da política de ciclo de vida; até então, preferir restrição a exclusão física com histórico relacionado.

### 4.4 `ServerBans`

Uma linha é um ciclo de banimento. Revogar atualiza a linha; um ban posterior cria novo ciclo.

| Campo | Tipo recomendado | Integridade |
|---|---|---|
| `id` | Inteiro, PK | Identificador imutável do ciclo |
| `server_id` | Inteiro, FK `servers.id` | Obrigatório, sem cascade histórico |
| `user_id` | Inteiro, FK `users.id` | Alvo obrigatório |
| `banned_by` | Inteiro, FK `users.id` | Ator obrigatório |
| `banned_at` | timestamp com timezone | Obrigatório, default `now()` |
| `reason` | TEXT | Opcional |
| `target_highest_role_position` | inteiro | Obrigatório, `CHECK >= 0`; snapshot antes de remover cargos |
| `revoked_by` | inteiro, FK `users.id` | Nulo quando ativo |
| `revoked_at` | timestamp com timezone | Nulo quando ativo |

Derivar ativo/revogado de `revoked_at IS NULL` evita estado booleano duplicado. Constraint exige `revoked_by` e `revoked_at` ambos nulos ou ambos preenchidos. Índice único parcial `(server_id,user_id) WHERE revoked_at IS NULL` impede ban ativo duplicado; índice `(server_id,banned_at DESC,id DESC)` atende listagem. Índice por ator ou motivo não é necessário sem consulta aprovada.

`target_highest_role_position` conserva a maior posição individual do alvo no instante do banimento, ou 0 sem cargos. Na revogação, membro comum exige `unban_members` e posição estritamente acima do snapshot. `@everyone` fica fora do snapshot.

### 4.5 `ServerAuditLogs`

Tabela de eventos imutáveis, separada de `ServerBans`.

| Campo | Tipo recomendado | Integridade |
|---|---|---|
| `id` | Inteiro, PK | ID histórico estável |
| `server_id` | Inteiro, FK `servers.id` | Obrigatório |
| `actor_user_id` | Inteiro, FK `users.id` | Responsável |
| `target_user_id` | Inteiro, FK `users.id` | Alvo; novo proprietário no evento de transferência |
| `action_type` | String/enum/check | `MEMBER_KICKED`, `MEMBER_BANNED`, `MEMBER_UNBANNED`, `OWNERSHIP_TRANSFERRED` |
| `created_at` | timestamp com timezone | Obrigatório, default `now()` |
| `reason` | TEXT | Opcional |
| `ban_id` | Inteiro, FK composta opcional | Obrigatório para eventos de ban/unban conforme decisão; nulo para kick/transferência |

Constraint limita tipos permitidos. Recomenda-se FK composta entre `ban_id`, `server_id` e `target_user_id` para assegurar que o evento referencia o ciclo do mesmo servidor e alvo. Índices `(server_id,created_at DESC,id DESC)` e `(server_id,action_type,created_at DESC,id DESC)` atendem consulta paginada e filtro por tipo.

Logs não expiram. FKs devem impedir exclusão em cascata e órfãos. Para preservar IDs durante anonimização, preferir manter usuário anonimizado com PK estável. Exclusão física de usuário/servidor requer decisão de ciclo de vida e política compatível com FKs restritivas.

### 4.6 Exclusão e relacionamentos ORM

O padrão atual é de FKs e consultas explícitas, sem `relationship()`. Mantê-lo nesta etapa evita cascades ORM inadvertidas e carregamento implícito de registros históricos; os serviços deverão usar joins e queries delimitados. O custo é mais código de consulta e necessidade de evitar N+1 explicitamente. Se `relationship()` vier a ser adotado, deve usar estratégia de carregamento explícita e não introduzir cascade destrutivo em bans/audit.

Recomendação de FKs: `RESTRICT`/`NO ACTION` para dados históricos e para servidores enquanto política de exclusão não for aprovada. A limpeza normal de cargos na saída é DELETE explícito das associações, dentro da transação, e não cascade de exclusão do usuário/servidor.

## 5. Schemas e endpoints

Schemas Pydantic existentes incluem `ServerRoleResponse`, usado na leitura atual dos cargos. Permanecem propostos: `ServerMemberResponse`, `MemberListResponse` ou paginação existente, `RoleCreate`, `RoleUpdate`, `MemberRoleChange`, `BanCreate`, `BanResponse`, `BanListResponse`, `AuditLogResponse`, `InviteCreate`, `InviteResponse` (token bruto somente na emissão), `InviteAccept` e `OwnershipTransfer`. O schema de atualização de `everyone_permissions` já existe. Schemas de mutação devem rejeitar campos extras sensíveis; ator, proprietário e permissões nunca vêm confiados do payload.

| Método e caminho | Finalidade | Autorização e validações | Respostas esperadas |
|---|---|---|---|
| `GET /servers/{server_id}/members?limit=20&offset=0` | Lista participação ativa, `joined_at DESC` e desempate estável | JWT e participação ativa do solicitante; não listar LEFT | 200; 404 para servidor não acessível; 422 para paginação inválida |
| `GET /servers/{server_id}/members/{user_id}` | Consultar um membro ativo | JWT; ator e alvo ativos; não revelar alvo inexistente/LEFT | 200/404 |
| `POST /servers/{server_id}/leave` | Saída do ator | JWT, membership ativo; proprietário transfere antes; limpar cargos e fechar participação atomicamente | 204; 409 em operação repetida/owner atual |
| `DELETE /servers/{server_id}/members/{user_id}` | Expulsão | Proprietário ou `kick_members` e hierarquia superior; alvo ativo; sem self-kick ou kick do proprietário; audit log | 204; 403 ou 404 conforme ocultação; 409 para estado conflitante |
| `POST /servers/{server_id}/bans` | Banir membro ativo | Proprietário ou `ban_members` + hierarquia superior; sem auto/owner-ban; snapshot e limpeza atômicos | 201; 403/404/409 conforme alvo/estado |
| `GET /servers/{server_id}/bans` | Listar banimentos com `status`, período e paginação | Proprietário: ativos e revogados; `unban_members`: ativos; kick/ban isolados sem acesso | 200 ou resposta de ocultação definida antes da API |
| `POST /servers/{server_id}/bans/{ban_id}/revoke` | Revogar ciclo ativo | Proprietário ou `unban_members` e hierarquia superior ao snapshot; não reativa participação | 200/204; 403/404/409 |
| `GET /servers/{server_id}/audit-logs` | Consultar logs com período/tipo e paginação | Só proprietário | 200 ou resposta de ocultação definida antes da API |
| `POST /servers/{server_id}/invites` | Emitir convite | Proprietário ou membro ativo com `manage_invites`; hash persistido; token bruto retornado uma vez | 201; 403/422 |
| `DELETE /servers/{server_id}/invites/{invite_id}` | Revogar convite | Proprietário ou `manage_invites`; sem remover histórico relacionado | 204; 403/404 |
| `POST /server-invites/accept` | Validar/consumir token e entrar/reativar | Usuário autenticado; verifica ban ativo antes de consumir; valida idade +18 conforme regra futura; membro ativo recebe 409 sem mutação | 200/201; 404/409/422 |
| `POST /servers/{server_id}/transfer-ownership` | Transferir propriedade | Proprietário atual; destino ativo e sem banimento; grava `ServerConfigHistory` e audit atomicamente | 200; 403/404/409 |
| `GET /servers/{server_id}/roles` | Listar cargos do servidor — **implementado** | JWT e participação `ACTIVE`; disponível a todos os membros ativos, sem exigir `manage_roles`; ordena por `position` crescente e `id` | Implementado |
| `GET /servers/{server_id}/roles/{role_id}` | Consultar um cargo — **implementado** | JWT e participação `ACTIVE`; cargo precisa pertencer ao servidor informado | Implementado; 404 para cargo inexistente ou de outro servidor |
| `POST /servers/{server_id}/roles` | Criar cargo | Proprietário ou `manage_roles`; membro comum cria abaixo da própria autoridade e concede somente permissões efetivas que já possui; campo reservado não vem do cliente | 201; 403/409/422 |
| `PATCH /servers/{server_id}/roles/{role_id}` | Alterar propriedades de cargo comum | Proprietário (sem hierarquia para cargos comuns) ou `manage_roles` com hierarquia estrita; cargos `is_system_role` imutáveis para todos; validar delta JSONB e alvos afetados | 200; 403/404/409/422 |
| `DELETE /servers/{server_id}/roles/{role_id}` | Excluir cargo comum | Proprietário (sem hierarquia para cargos comuns) ou `manage_roles` com hierarquia estrita; cargo reservado não pode ser excluído; atribuições existentes causam `409` | 204; 403/404/409 |
| `POST /servers/{server_id}/members/{user_id}/roles/{role_id}` | Atribuir cargo a membro | Ator e alvo ativos; IDs no mesmo servidor; `manage_roles`; hierarquia do ator, cargo e alvo; comparar permissões efetivas antes/depois e não conceder ao alvo permissão que o ator não possui | 201; 403/404/409 |
| `DELETE /servers/{server_id}/members/{user_id}/roles/{role_id}` | Remover atribuição | Mesmas validações de autorização/hierarquia; sem modificar relação de outro servidor | 204; 403/404/409 |
| `PUT /servers/{server_id}/channels/{channel_id}/roles/{role_id}` | Autorizar cargo em canal privado | Somente proprietário; IDs do mesmo servidor; `@everyone` proibido; auditar e alterar atomicamente | 204; 403/404/409 |
| `DELETE /servers/{server_id}/channels/{channel_id}/roles/{role_id}` | Revogar acesso de cargo | Somente proprietário; auditar e alterar atomicamente; preservar acesso do proprietário | 204; 403/404 |
| `PATCH /servers/{server_id}/everyone-permissions` | Atualizar grants gerais de `@everyone` — **implementado** | Somente proprietário ativo; substituição integral; seis permissões documentadas, booleanos estritos, sem chaves extras; histórico antes/depois em `ServerConfigHistory` na mesma transação | Implementado; testes registrados no status do projeto |

O uso de `403` ou `404` em listagens de bans/logs não está aprovado em detalhe; definir política uniforme de ocultação antes de expor dados. O `@everyone` privado já foi decidido: não conceder acesso. A autorização funcional para editar canais permanece dependente do catálogo de permissões desses recursos.

As autorizações para essas duas configurações estão aprovadas: edição de `everyone_permissions` e configuração de cargos autorizados em canais privados são exclusivas do proprietário. `manage_roles` não as concede. O endpoint de canal só altera a associação canal-cargo e deve auditar cada concessão/remoção; o endpoint de `everyone_permissions` deve registrar valores anterior/novo em `ServerConfigHistory`. A escolha da representação física da associação canal-cargo continua técnica e precisa ser concluída no bloco de canais.

## 6. Serviço central de autorização e gestão de cargos

O serviço central de autorização existe em `app/services/server_authorization_service.py` e usa o catálogo de `app/server_permissions.py`. Ele resolve grants de `everyone_permissions` e dos cargos individuais para membros ativos, calcula o nível hierárquico e compara ator/alvo para o requisito hierárquico, mantendo `is_owner` separado. A comparação não substitui a permissão funcional e o serviço não concede acesso a canais privados. A gestão futura deve reutilizar esse serviço sem duplicar checks nos routers:

1. Resolver servidor pelo ID e identidade do usuário autenticado.
2. Obter a participação do ator no servidor e exigir `ACTIVE` para operações internas.
3. Reconhecer proprietário comparando `Server.owner_id` com o usuário autenticado; não inferir propriedade por cargo.
4. Reutilizar a união existente de permissões de `everyone_permissions` e de todos os cargos individuais, baseada em grants booleanos verdadeiros.
5. `get_member_hierarchy_level(db, server_id, user_id)` e `is_hierarchy_comparison_approved(db, server_id, actor_user_id, target_user_id)` estão implementadas em `app/services/server_authorization_service.py`. A comparação valida ator/alvo `ACTIVE` no mesmo servidor; ausência/LEFT resulta em 404. Proprietário pode agir sobre membro ativo independentemente da posição; membro comum exige posição estritamente superior e não age sobre o proprietário. Autoação, igualdade e nível inferior retornam `False`. O ID do ator vem do principal autenticado. O retorno não substitui a permissão específica; `ResolvedServerPermissions.is_owner` continua representando separadamente a autoridade especial.
6. Nas futuras operações, aplicar a exceção hierárquica do proprietário aprovada, validar separadamente a permissão funcional e usar o comparador central quando a regra exigir hierarquia.
7. Para unban, comparar com `target_highest_role_position`; para cargo, validar posição e hierarquia do alvo antes da mutação.
8. Não retornar objeto ou metadado antes da autorização; todas as queries incluem `server_id` e associação válida.
9. A atualização de `everyone_permissions` já exige proprietário real, valida o conteúdo no backend e persiste o histórico antes/depois na mesma transação; manter esse contrato se o serviço for reorganizado, sem inferir autoridade de `manage_roles`.
10. Para configurar acesso de canal privado, exigir proprietário real, confirmar canal e cargo no mesmo servidor, rejeitar `@everyone`, gravar a concessão/remoção de associação e evento de auditoria no mesmo commit. `manage_roles` não autoriza a operação.

### Fluxo de atribuição/remoção de cargo

Sob transação e locks consistentes:

1. Autenticar o ator; lock do servidor e resolver se é proprietário ou membro ativo.
2. Para não proprietário, exigir `manage_roles` (permissão independente).
3. Buscar cargo, participação alvo e servidor pelas relações reais; verificar IDs combinam no mesmo servidor e ator/alvo estão `ACTIVE`.
4. Se `role.is_system_role` for verdadeiro, negar qualquer alteração ou exclusão, inclusive pelo proprietário; não usar `is_default`, nome ou posição para identificar a reserva.
5. Para ator não proprietário, calcular sua autoridade máxima atual e exigir `role.position < actor_highest_position`; posição igual não passa. O proprietário não depende da hierarquia para cargos comuns.
6. Para ator não proprietário, se o alvo for outra pessoa, exigir hierarquia estritamente superior à do alvo e impedir que a atribuição final eleve o alvo acima do ator. Aplicar regras contra autopromoção e escalada também em atribuição própria. A autoridade do proprietário continua limitada pela imutabilidade de cargos `is_system_role`.
7. Não permitir que um `role_id`, `member_id`, `server_id` ou `is_system_role` do cliente substitua a consulta de autorização; validar novamente após locks.
8. Inserir/remover a linha de `ServerMemberRole` e fazer commit único. Capturar conflito da unicidade como erro controlado; rollback em qualquer falha.

Para criar/editar permissões JSONB, calcular permissões efetivas do ator e dos membros ativos afetados antes e depois da proposta. Membro comum exige `manage_roles` e as regras de cargo, alvo e sistema reservado; para cada nova concessão, verificar que o ator já possui essa permissão efetivamente. Validar as chaves pelo catálogo aprovado. Ao atribuir um cargo, comparar o delta efetivo do alvo; uma linha de associação não pode ser usada para conceder capacidade que o ator não tem. O proprietário pode configurar todas as permissões aprovadas em cargos comuns e está isento do teto de concessão, mas não pode modificar cargo `is_system_role`.

## 7. Fluxos de domínio e transações

### Saída, kick e ban

- **Saída:** lock servidor/participação; rejeitar se `LEFT`; recusar proprietário atual; excluir atribuições; marcar `LEFT` e `left_at`; commit. Não criar banimento.
- **Kick:** lock servidor/ator/alvo; verificar alvo `ACTIVE`, não ser proprietário nem o próprio ator; autorizar `kick_members` e hierarquia ou proprietário; excluir cargos, fechar participação e criar `MEMBER_KICKED` no mesmo commit.
- **Ban:** autorizar `ban_members` + hierarquia ou proprietário; alvo precisa `ACTIVE` e não pode ser ator/proprietário; capturar snapshot antes de remover cargos; criar ciclo ativo, log `MEMBER_BANNED`, excluir associações e marcar `LEFT` na mesma transação.
- **Unban:** exigir ciclo ativo; autorizar `unban_members` e hierarquia superior ao snapshot ou proprietário; preencher autor/data de revogação e registrar `MEMBER_UNBANNED`; não reativar usuário.

### Convites e reentrada

- Criar token aleatório de alta entropia; enviar bruto somente uma vez e guardar hash. Validar expiração, revogação, limite de usos e servidor.
- Na aceitação, adquirir locks e consultar banimento antes de consumir convite. Participação já ativa responde `409` sem mutar contagem, cargos, permissões ou `joined_at`.
- Sem ban ativo, consumir convite e criar/reutilizar participação no mesmo commit; reentrada limpa `left_at`, atualiza `joined_at` e não restaura cargos.
- Impedir que duas aceitações concorrentes ultrapassem `max_uses` ou dupliquem a participação. Usar `SELECT FOR UPDATE` no convite e participação existente, além da constraint única atual.

### Transferência e auditoria

- Lock no servidor; confirmar proprietário atual e destino ativo/não banido; alterar `owner_id`; adicionar histórico de configuração e `OWNERSHIP_TRANSFERRED`. Tudo em transação única.
- Novo proprietário recebe imediatamente autoridade especial; antigo perde essa autoridade. Falha em qualquer gravação reverte estado e logs.
- Auditoria não faz commit independente. Sem cascade para logs; nenhuma expiração automática.

### Locking e condição de corrida

Para a primeira versão, usar ordem única: servidor, convite (se houver), participações (ordenadas por ID), cargos/associações (ordenados), ciclo de banimento. Bloquear o servidor (`SELECT FOR UPDATE`) nas mutações concorrentes do mesmo servidor simplifica conflito entre entrada, banimento, saída e transferência, à custa de serialização por servidor. Revalidar status após obter locks. Constraints únicas e checks permanecem como última defesa. Uma política mais granular pode ser avaliada depois de medir contenção; não implementar retries automáticos não aprovados.

## 8. Migrations planejadas

1. **Concluído no repositório:** revisão `8a62d13e4f90` adiciona `server_roles.is_system_role` e `servers.everyone_permissions` JSONB com default `{}`, `NOT NULL` e constraint de objeto. Não duplicar esses campos em migration futura. A revisão aplicada ao banco de desenvolvimento não é afirmada aqui.
2. **Concluído para posição:** preflight autorizado encontrou zero registros e zero posições inválidas. Removido o default Python `0`; não há default no banco; modelo e migration `990fa9af113d` adicionam `ck_server_roles_position_positive` (`position >= 1`). Posições repetidas continuam válidas. Upgrade/downgrade foram testados em PostgreSQL descartável. Não houve backfill; a identificação dos cargos reservados continua independente e pendente de aprovação.
3. **Banimentos:** nova tabela com snapshot, autor, alvo, status por revogação, checks, FKs restritivas e índice único parcial ativo.
4. **Auditoria:** tabela separada, eventos de membros/transferência e concessão/revogação de acesso canal-cargo, referência composta opcional/obrigatória aos ciclos de ban, índices de timeline e filtro.
5. **Canais privados:** adicionar `is_private`, unique `(id,server_id)` a canais e tabela de associação canal-cargo com chaves compostas. `@everyone` não terá linha de associação. Configuração exclusiva do proprietário; cada alteração da associação e o log correspondente são atômicos.
6. **Convites, membros, cargos e transferência:** reutilizam as tabelas atuais; nenhuma migration é prevista salvo índices justificados por consultas reais.

A regra de teto de concessões de permissões por membro comum usa `ServerRole.permissions` JSONB e o resolvedor existente; por si só, não exige migration. A validação estrutural de posição foi concluída pela migration `990fa9af113d`, que adiciona somente `ck_server_roles_position_positive`; ela não altera `is_system_role` ou `everyone_permissions`. A revisão foi validada em PostgreSQL descartável com upgrade e downgrade. Não há migration de posição pendente. Migrações de outras funcionalidades planejadas permanecem nas seções correspondentes.

Não criar uma única migration grande para todas essas estruturas. Gerar revisões pequenas encadeadas, comparar metadata e histórico existente, revisar downgrade e aplicar somente no banco de testes para verificação depois da autorização de implementação. Não executar migration nesta etapa.

### Diagnóstico seguro de `is_default`

O código usa `is_default` no modelo `ServerRole` e no índice único parcial `uq_server_roles_one_default`; a migration `457fe8255da3` cria a coluna `NOT NULL` sem default de banco e esse índice, cujo downgrade o remove. O modelo fornece default Python `False`. `ServerRoleResponse` inclui o campo na leitura de cargos, mas nenhum serviço ou rota usa seu valor para regra funcional; isso não atribui finalidade nova ao campo. O índice permite no máximo um cargo marcado por servidor.

Não foi consultado o banco de desenvolvimento ou o de testes. Para verificar registros existentes, executar apenas após autorização e escolha explícita do ambiente:

```sql
SELECT id, server_id, name, position, is_default
FROM server_roles
WHERE is_default IS TRUE
ORDER BY server_id, id;
```

Decisão aprovada para esta etapa: preservar campo e índice, sem associar a `@everyone`, sem nova finalidade e sem remoção. O destino futuro depende dos dados e de justificativa funcional.

## 9. Matriz de testes

Todos os testes de integração usam `plataforma_tcc_test` (`127.0.0.1:55432`), guardas atuais de `tests/conftest.py` e credenciais/segredo sintéticos. Não executar testes contra banco de desenvolvimento. O cálculo e a comparação hierárquica foram cobertos por **34 testes de autorização aprovados**; a suíte completa mais recente foi **125 passed, 0 failed**.

| Grupo | Casos de segurança/integridade |
|---|---|
| Autenticação | Sem token, inválido/expirado, usuário inativo; todas as rotas sensíveis protegidas |
| Participação/IDOR | Membro ativo acessa; usuário alheio e membro LEFT negados; tentativa com IDs cruzados de servidor não vaza dados |
| Membros | Lista apenas ACTIVE e paginada; consulta alvo ACTIVE; saída/expulsão repetida falha; owner não sai sem transferir |
| `manage_roles` | Independência de `manage_invites`/outras permissões; falta da permissão nega; grant explicitamente em cargo permite sujeito à hierarquia; autorização no backend |
| Cargo/hierarquia | Posição abaixo passa; igual/acima falha; ator sem cargo nível 0; maior entre cargos; `@everyone` ignorado; sem autopromoção ou elevação do alvo |
| Cargos e leitura | Todo membro `ACTIVE` autenticado lista/consulta; `LEFT` é negado; leitura não autoriza mutação |
| Cargo reservado | `is_system_role` bloqueia edição estrutural e exclusão para todos, inclusive proprietário; não inferir por nome/posição nem usar `is_default` |
| Exclusão | Cargo com qualquer associação em `ServerMemberRole` retorna `409`; associação e permissões de membros permanecem intactas |
| Atribuição | Ator/alvo/cargo/server devem corresponder; dois cargos permitidos sem duplicidade; atribuição a LEFT rejeitada; transação/rollback |
| Permissões JSONB | União de grants; `false` não anula `true`; ausência não concede; permissões administrativas genéricas não implicam as cinco chaves; membro não concede chave que não possui efetivamente; dono pode conceder todas as aprovadas |
| Edição de cargo | Calcular diff de concessões; impedir grant de `manage_roles` ou outra capacidade que exceda ator; validar posição do cargo e hierarquia de cada membro ativo afetado |
| Atribuição de cargo | Comparar permissões efetivas do alvo antes/depois; negar novo grant que o ator não possui; proteger autoatribuição e elevação indireta; owner bypass |
| `@everyone` e canais | `everyone_permissions` une grants gerais, mas jamais revela canal privado; acesso exige role autorizado; owner bypass; usuário LEFT/outro servidor negados |
| Configuração do `@everyone` | Não proprietário, inclusive com `manage_roles`, recebe 403; proprietário altera; catálogo/formato inválido rejeitado; histórico antes/depois é criado; falha no log reverte a configuração; nova união vale imediatamente para ativos |
| Configuração de acesso a canal privado | Não proprietário, inclusive com `manage_roles`, não configura associação; proprietário concede/revoga; `@everyone` é rejeitado; cargo/canal de outro servidor são rejeitados; auditoria acompanha a alteração; falha em qualquer gravação causa rollback; owner sempre acessa |
| Kick/ban/unban | Independência de permissões; hierarchy inferior/igual/superior; exceção do owner; proteção de self/owner; snapshot antes de apagar roles; atomicidade com audit |
| Convites | Hash sem token bruto; válido, expirado, revogado, esgotado; limite sob concorrência; banned não consome; ACTIVE dá 409 sem mudança; reentrada atualiza data e não restaura cargos |
| Consulta de bans/logs | Owner vê todos; `unban_members` apenas ativos; kick/ban não autorizam lista; audit só owner; filtros e paginação |
| Transferência | Destino ativo e não banido; qualquer cargo; novo/antigo owner alternam autoridade; owner_id, config history e audit atômicos |
| Auditoria/privacidade | Quatro tipos, referência a ban correto, sem expiração/cascade; anonimização mantém IDs; física exclusão conforme política aprovada |
| Concorrência/rollback | Aceites no último uso, ban versus entrada, duas reentradas, atribuição versus saída, transfer versus saída; falha simulada não deixa estado parcial |
| Regressão | Suítes de usuários, conversas e mensagens continuam aprovadas após integração |

Testes de acesso a canais privados só se tornam executáveis quando modelo/rotas de canal forem implementados. Não testar `@everyone` como autorizador positivo; a regra aprovada é negar esse acesso.

## 10. Blocos de implementação e dependências

| Bloco | Escopo e arquivos prováveis | Migration | Testes e critério de conclusão |
|---|---|---|---|
| 1. Leitura de cargos — **concluído** | Criados `app/routers/server_roles.py`, `app/services/server_role_service.py` e `tests/test_server_roles.py`; alterados `app/schemas.py` (schema `ServerRoleResponse`) e `app/main.py` (registro do router). Reutiliza `require_active_server_membership` e `ServerRole` | Nenhuma | 7 testes específicos passaram; cobrem autenticação, membro ativo/proprietário, não membro/LEFT, detalhe, cargo ausente/de outro servidor, isolamento e leitura sem `manage_roles`. Lista ordenada por `position` crescente e `id` como desempate |
| 2. Preflight e validação de posições — **concluído** | Preflight autorizado identificou 0 servidores, 0 cargos, 0 atribuições, 0 posições inválidas e 0 cargos `is_default=true`; default Python removido e constraint adicionada ao modelo. Não houve backfill | Migration `990fa9af113d`, encadeada após `8a62d13e4f90`, adiciona somente `ck_server_roles_position_positive` (`position >= 1`). Validada em PostgreSQL descartável com upgrade e downgrade; nenhuma migration aplicada aos bancos de desenvolvimento ou testes | 7 testes específicos passaram; cobrem posição 1 e outros valores positivos, rejeição de zero e negativo pelo banco, posições repetidas e ausência de default/coerção para zero. Suíte completa: 102 passed |
| 3. Cálculo e comparação hierárquica — **concluído** | `get_member_hierarchy_level(...)` e `is_hierarchy_comparison_approved(...)` em `app/services/server_authorization_service.py`; valida ator/alvo `ACTIVE` e aplica superioridade estrita para membros comuns, com exceção do proprietário | Nenhuma | Sem cargos retorna 0; `@everyone` não influencia; LEFT/inexistente retorna 404; autoação/igualdade/inferioridade e alvo proprietário por membro comum retornam `False`; proprietário passa para membro ativo sem depender da posição; comparação não concede permissão funcional e o ator vem do principal autenticado. 34 testes de autorização passaram; suíte completa: 125 passed |
| 4. Criação e edição de cargos | Schemas estritos, service e router de cargos; usar resolvedor e comparador central do bloco 3 e `is_system_role`. A integração das regras de autoridade continua pendente | Nenhuma para campos já existentes; constraint de posição do bloco 2 concluída | Owner gerencia cargos comuns; membro comum exige `manage_roles`, posição e limites de concessão; campos de controle não são aceitos do cliente; JSONB só aceita catálogo e booleanos estritos; sem escalada direta/indireta ou alteração parcial |
| 5. Atribuição e remoção de cargos | Operações de associação no serviço/router; reutilizar `ServerMemberRole`, membro e role existentes | Nenhuma prevista; as FKs compostas e unicidade atuais dão base de integridade | Ator/alvo/cargo no mesmo servidor e ativos; verificar autorização, hierarquia e grants efetivos antes/depois; impedir autopromoção, atribuição cruzada e duplicidade; transação/concorrência/rollback cobertos |
| 6. Exclusão de cargos | Exclusão de cargo comum pelo serviço/router, conferindo `is_system_role` e atribuições existentes | Nenhuma prevista; FK restringe referências e regra de produto exige `409` enquanto atribuído | Reservado nunca excluído; cargo atribuído retorna `409` sem remover vínculos; cargo comum vazio pode ser excluído; corrida com atribuição não deixa estado inconsistente |
| 7. Testes de integração e regressão | Completar testes de API e autorização dos blocos anteriores e executar a suíte completa no PostgreSQL isolado | Nenhuma | Matriz de autenticação, IDOR, owner, `manage_roles`, hierarquia, escalada, cargos reservados, concorrência e rollback aprovada; regressões existentes passam |
| 8. Dados de banimento e auditoria | Criar modelos `ServerBan` e `ServerAuditLog`, registrar em `models/__init__.py` e serviços transacionais | Tabelas e constraints/índices separados | Ciclo ativo único, snapshot e FKs de audit íntegros |
| 9. Expulsão e banimentos | Serviço de moderação e rotas de kick/ban/unban/consulta; integra autorização e participação existente | Tabelas do bloco 8 | Logs, snapshot, status e cargos atômicos; matriz de permissão completa |
| 10. Transferência de propriedade | Serviço/router/schema usando `Server.owner_id` e `ServerConfigHistory` | Sem tabela nova | Novo owner, histórico e audit consistentes numa transação |
| 11. Convites | Serviço/router/schema; aceitação chama a primitiva interna de reentrada e valida bans | Reutiliza `ServerInvite`, salvo índice justificado | Uso limitado sob concorrência, sem bypass e sem reentrada com cargos antigos |
| 12. Canal privado | Alterar `ServerChannel`; criar `ServerChannelRole`; configuração owner-only e guard de acesso ao conteúdo | Coluna `is_private`, unique composta e associação; reutiliza audit | IDOR bloqueado; `@everyone` nunca concede; owner bypass; só owner altera; concessões/revogações auditadas e atômicas |

O núcleo de participação, o resolvedor de grants, o endpoint de configuração de `@everyone`, a leitura de cargos, a validação estrutural de posições, o cálculo de nível e a comparação hierárquica centralizada estão implementados. A comparação exige ator/alvo ativos, aplica superioridade estrita a membros comuns e trata o proprietário separadamente; não substitui a permissão funcional da operação. Foram 34 testes de autorização aprovados e a suíte completa mais recente foi `125 passed, 0 failed`, exclusivamente em `plataforma_tcc_test` (`127.0.0.1:55432`). A migration `990fa9af113d` foi validada em PostgreSQL descartável com upgrade e downgrade; nenhuma migration foi aplicada aos bancos de desenvolvimento ou testes. Permanecem pendentes a integração do comparador com gerenciamento de cargos e kick/ban/unban, as regras operacionais de autoridade e as operações de criação/edição/atribuição/remoção/exclusão. A proteção de `is_system_role` depende do mapeamento aprovado dos cargos reservados; não marcar nenhum por inferência. O serviço interno de reentrada necessário a convites será definido no bloco de convites/membros; transferência ainda depende de auditoria e a saída do proprietário permanece bloqueada até essa etapa existir.

## 11. Schemas e responsabilidades de autorização

Schemas devem validar forma e limites (IDs positivos, posição positiva, strings, paginação e tipos booleanos no JSONB); autorização permanece nos serviços. `RoleCreate` e `RoleUpdate` devem rejeitar campos desconhecidos e nunca aceitar `server_id`, `assigned_by`, `owner_id`, `is_default` ou `is_system_role` como valores controlados pelo cliente. O campo `is_system_role` já existe; qualquer classificação dos registros exige mapeamento aprovado e operação controlada, sem inferência. O schema pode validar chaves do catálogo aprovado, mas somente o serviço calcula a diferença de permissões e verifica se o ator pode conceder cada grant.

Serviço de membros cuida de estados e limpeza. Serviço de cargos valida função, hierarquia, servidor e associação; calcula permissões efetivas do ator e dos membros afetados antes/depois; limita concessões novas ao conjunto efetivo do ator não proprietário; permite ao proprietário todas as permissões aprovadas; e valida novamente grants decorrentes de atribuição. Serviço de bans calcula snapshot e grava evento. Serviço de convites persiste hash e controla limite. Serviço de transferência atualiza servidor, histórico e audit. A camada de router autentica e converte o serviço em resposta; não duplica regras.

Para canais privados, o guard recebe identidade autenticada, servidor/canal, participação ativa e cargos individuais reais. Não pode consultar `everyone_permissions` para decidir a associação autorizadora. Permissões funcionais de ação, quando seu catálogo for aprovado, são avaliadas depois de estabelecer acesso ao canal.

## 12. Pendências e riscos

### Decisões de negócio ainda não aprovadas

- Catálogo e semântica de permissões de canais e mensagens além das cinco permissões da Etapa 2.
- Finalidade futura de `ServerRole.is_default`; por ora permanece e não representa `@everyone`.
- Detalhamento dos limites para permissões funcionais em JSONB além do teto aprovado de concessão por membro comum, sem reabrir essa regra.
- Eventos de auditoria além dos eventos aprovados para membros, transferência e acesso de cargos a canais privados, incluindo eventual auditoria de atribuições de cargos e saída voluntária.
- Política HTTP exata para ocultar bans, logs e outros recursos privados.
- Ciclo de vida de servidor/canal e política de exclusão física.
- Fonte/estado da verificação de idade para servidores +18.

### Detalhes técnicos definíveis durante implementação

- Tipos SQLAlchemy/DDL, nomes físicos, checks, índices, paginação e serialização JSONB conforme as decisões já aprovadas.
- Hash de token aleatório de alta entropia e não exposição do segredo em logs/URLs.
- Locks `SELECT FOR UPDATE`, ordem uniforme e tratamento de conflito/deadlock com rollback.
- Respostas exatas para condições ausentes/conflitantes, respeitando ocultação.
- FKs restritivas e anonimização mantendo IDs; sem cascade que apague auditoria.
- Implementar comparação do delta JSONB e das permissões efetivas dos alvos antes/depois; o teto de concessão por membro comum está aprovado.
- A classificação explícita dos registros existentes para `is_system_role = true`, depois da definição aprovada da lista de cargos reservados.

### Dependências que bloqueiam blocos

- A migration que adiciona `is_system_role` já existe no repositório; o campo não deve ser recriado. A lista e o mapeamento dos cargos reservados continuam pendentes. Antes de liberar mutações, a proteção deve ser aplicada no backend e o mapeamento aprovado deve ser executado de forma controlada; não classificar por nome ou posição.
- Edição e atribuição de cargos dependem tecnicamente do serviço central implementar o teto aprovado de permissões efetivas e testes de escalada direta/indireta.
- A configuração de `everyone_permissions` já está implementada e não é dependência pendente. A configuração de acesso privado depende do modelo de canal-cargo e da tabela de auditoria; a autoridade do proprietário para essa configuração já está aprovada.
- Testes de canal privado dependem da migration e do guard de acesso do bloco 8.
- O cálculo e a comparação de nível estão implementados no bloco 3; a integração com gerenciamento de cargos e kick/ban/unban, além das regras operacionais de autoridade, continua pendente.
- Ban/unban depende dos modelos de bans/audit e do serviço central; convite depende dos serviços de membro e ban.

### Riscos

1. Permissão checada sem participação ativa ou hierarquia permite escalada de privilégio.
2. Reusar `is_default` para `@everyone` ou para papel reservado contradiz a decisão e mascara finalidade.
3. Usar `everyone_permissions` como autorização privada dá acesso indevido; o guard deve depender somente da associação de cargos individuais autorizados e do owner bypass.
4. Modificar cargo de posição menor ou atribuí-lo pode escalar permissões por JSONB se o serviço não aplicar o teto aprovado ao delta do ator e às permissões efetivas dos alvos.
5. Calcular o snapshot depois de limpar cargos apaga a hierarquia de referência para unban.
6. Sem locks, aceitação de convites pode ultrapassar limite ou competir com banimento/saída.
7. Cascade em usuário/servidor pode violar preservação de audit e bans.
8. O preflight atual encontrou zero posições inválidas, mas eventual dado legado inválido em outro ambiente exigiria nova avaliação; backfill automático poderia inventar hierarquia e não deve ser feito por heurística.
9. O modelo não vincula owner a uma participação ACTIVE por constraint; criação/transferência deve manter essa invariável na transação.

## 13. Arquivos examinados e rastreabilidade

Documentação lida: `AGENTS.md`, `CONTEXTO_TCC.md`, `STATUS_PROJETO.md`, `ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md` e planejamento técnico anterior apresentado na conversa.

Código e artefatos verificados na análise técnica anterior e confirmados nos documentos atuais: `app/models/server.py`, `server_member.py`, `server_role.py`, `server_member_role.py`, `server_channel.py`, `server_invite.py`, `server_config_history.py`, `app/models/__init__.py`, `app/schemas.py`, `app/routers/servers.py`, `app/routers/server_members.py`, `app/routers/server_roles.py`, `app/services/server_service.py`, `app/services/server_member_service.py`, `app/services/server_role_service.py`, `app/services/server_authorization_service.py`, `app/auth.py`, `app/database.py`, `app/settings.py`, `app/main.py`, `migrations/env.py`, `alembic.ini`, `migrations/versions/457fe8255da3_add_servers_and_channels.py`, `tests/conftest.py`, `tests/test_servers.py`, `tests/test_server_members.py`, `tests/test_server_roles.py`, `docker-compose.test.yml` e `pytest.ini`.

Este arquivo é planejamento. Nenhuma implementação, migration, execução de teste, consulta de banco, commit ou push faz parte dele.
