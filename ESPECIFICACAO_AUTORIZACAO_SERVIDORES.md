# Especificação técnica: autorização e permissões de servidores

**Estado:** decisões aprovadas e implementação parcial. Estão implementados o CRUD básico de servidores e cargos, o núcleo de participação, atribuição/remoção manual de cargos, resolução de grants, cálculo e comparação hierárquica, configuração owner-only de `everyone_permissions`, convites, kick/ban/unban e consultas de banimentos/auditoria. Transferência de propriedade, canais privados e mensagens de canal estão implementados. A presença de regras ou modelos, isoladamente, não comprova que um fluxo esteja implementado.

**Escopo:** proprietário, membros, cargos, permissões, canais privados e menções coletivas em servidores.

Esta especificação complementa [CONTEXTO_TCC.md](CONTEXTO_TCC.md). O estado do código, das tabelas e das rotas está em [STATUS_PROJETO.md](STATUS_PROJETO.md). Regras aqui descritas não devem ser tratadas como funcionalidades existentes.

## 1. Princípios de autorização

1. Toda autorização é validada no backend em cada operação. A interface pode ocultar ações, mas não é uma fronteira de segurança.
2. Conhecer ou adivinhar o ID de um servidor, membro, canal, cargo, convite ou mensagem não concede acesso ao objeto.
3. Somente membros com participação `ACTIVE` participam das permissões e podem acessar operações e conteúdo do servidor. Um membro `LEFT` perde esse acesso.
4. As permissões comuns de um membro vêm do papel implícito `@everyone` e da união das permissões concedidas pelos cargos individuais atribuídos ao membro ativo.
5. A hierarquia de cargos determina quem pode gerenciar cargos de outras pessoas; posição hierárquica, por si só, não concede permissões funcionais.
6. A decisão específica de acesso a um canal privado prevalece sobre uma permissão geral de visualizar canais do servidor. Sem acesso ao canal, a API não retorna conteúdo ou dados do canal.
7. O proprietário tem autoridade administrativa especial, separada dos cargos e de suas posições, e precisa permanecer como membro ativo.

## 2. Proprietário do servidor

- O usuário autenticado que cria o servidor torna-se seu proprietário. O backend define o proprietário; a criação não aceita um `owner_id` arbitrário confiado ao cliente.
- A criação também cria o registro desse usuário em `server_members` com status `ACTIVE`.
- A autoridade administrativa do proprietário é especial e independe de cargo, inclusive de `@everyone`.
- Outro membro, inclusive alguém com cargo de administrador ou moderador, não pode remover o proprietário, alterar sua autoridade ou transferir a propriedade em seu nome.
- Outro membro também não pode banir o proprietário.
- Outro membro também não pode expulsar o proprietário.
- O proprietário não pode sair enquanto ainda for proprietário. Antes de sair, transfere a propriedade a outro membro ativo e elegível.
- Qualquer membro ativo que satisfaça os critérios de elegibilidade pode receber a propriedade; não é necessário possuir cargo de administrador ou outro cargo específico. A transferência deve ser iniciada pelo proprietário atual e validada pelo backend.
- A transferência atualiza o proprietário e registra o evento de auditoria na mesma transação. `ServerConfigHistory` é a tabela existente para esse histórico; `setting_name` pode identificar `owner_id`, com os valores anterior e novo registrados como texto.
- A transferência também gera o evento `OWNERSHIP_TRANSFERRED` em `ServerAuditLogs`, na mesma transação. O ator é o proprietário anterior e o alvo é o novo proprietário; o evento registra servidor, ator, alvo, data/hora e justificativa opcional. `ServerConfigHistory` preserva a mudança de configuração `owner_id`, enquanto `ServerAuditLogs` registra o evento de negócio.
- Falha ao atualizar o proprietário ou gravar a auditoria deve reverter a operação inteira.
- O novo proprietário deve ser membro `ACTIVE` e não banido no mesmo servidor, independentemente de cargo administrativo. As autoridades especiais passam imediatamente ao novo proprietário e deixam de valer para o antigo.

## 3. Cargos e hierarquia

### 3.1 Atribuição e posição

- Um membro ativo pode possuir vários cargos individuais simultaneamente.
- Novos membros não recebem cargo individual automaticamente.
- `@everyone` é implícito e não é um cargo individual registrado em `server_member_roles` para cada membro.
- Quanto maior `ServerRole.position`, maior a autoridade hierárquica do cargo.
- Para um membro com vários cargos individuais, sua hierarquia efetiva é a maior `position` entre esses cargos. Cargos com posições maiores têm hierarquia superior. `@everyone` não participa desse cálculo; o membro sem cargos individuais tem nível 0, reservado a esse caso. Cargos individuais devem ter `position >= 1`.
- Um administrador/moderador não pode gerenciar cargos de posição igual ou superior à sua. Um membro não pode atribuir a outra pessoa cargo superior ao próprio nível hierárquico.
- O proprietário pode administrar cargos comuns independentemente da hierarquia. Cargos reservados ao sistema são exceção: nem mesmo o proprietário pode excluí-los ou modificar suas propriedades estruturais.
- Posição controla principalmente a autoridade para gerenciar cargos. Ela não concede automaticamente permissões funcionais como enviar mensagens, gerenciar canais, expulsar, banir ou revogar banimentos.
- Nas operações de expulsão, banimento e revogação de banimento, membros de mesma hierarquia não podem agir uns contra os outros. Para cargos individuais, isso exige comparação estrita: o ator deve ter nível efetivo superior ao alvo.
- A configuração de permissões de `@everyone` é separada das atribuições individuais armazenadas em `server_member_roles`; ela não participa do cálculo da hierarquia.

### 3.2 Permissões combinadas

Semanticamente, as permissões efetivas de um membro ativo são a união das permissões concedidas por `@everyone` e pelos cargos individuais atribuídos a esse membro:

```text
permissoes_efetivas(membro) = permissoes_@everyone
                             ∪ permissoes_de_cada_cargo_atribuido
```

- Se qualquer cargo conceder uma permissão, o membro a possui.
- A ausência de uma permissão em outro cargo não a remove.
- Não implementar negação por cargo que anule concessão de outro cargo.
- A hierarquia de cargos é calculada separadamente; cargo de posição maior não recebe permissões funcionais por esse motivo.
- O proprietário tem autoridade administrativa especial e não depende dessa união para ações de administração do servidor.

As permissões independentes aprovadas para a Etapa 2 são `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles`. Nenhuma concede outra implicitamente, inclusive permissões administrativas genéricas. `mention_everyone` também é uma permissão documentada, específica para menções coletivas, e não se confunde com essas cinco permissões independentes. O resolvedor central reconhece essas seis chaves, considera grant somente quando o valor JSON é booleano `true`, ignora chaves desconhecidas e combina as concessões por união. Os schemas e serviços do CRUD de cargos validam essas chaves e booleanos estritos para criação/edição; a edição substitui as permissões do catálogo e preserva chaves legadas quando o campo é enviado.

`manage_roles` autoriza a gestão funcional de cargos, mas não elimina as restrições hierárquicas:

- O proprietário pode gerenciar qualquer cargo comum, sem depender de `manage_roles` ou comparação hierárquica; cargos marcados como reservados ao sistema são imutáveis para todos, inclusive para o proprietário.
- Outro membro precisa estar ativo, possuir `manage_roles` e só pode modificar cargos com posição estritamente inferior à sua maior posição individual.
- O membro não pode alterar cargo de posição igual ou superior, nem promover a si próprio ou outra pessoa acima da própria autoridade.
- Ao alterar atribuições de cargos de outro membro, a hierarquia do alvo também deve ser verificada; um membro comum não pode agir sobre alvo de hierarquia igual ou superior.
- Membros comuns não podem modificar cargos reservados ao sistema; a proteção também se aplica ao proprietário. A identificação é feita pelo campo próprio `ServerRole.is_system_role`, independente de `is_default`, e não pode depender de nome ou posição. O campo está no modelo e na revisão `8a62d13e4f90`; os serviços de edição e exclusão aplicam a proteção no backend. A lista exata dos cargos reservados e o mapeamento dos registros continuam pendentes.

O proprietário pode configurar todas as permissões aprovadas em cargos comuns; cargos `is_system_role` permanecem imutáveis inclusive para ele. Um membro comum com `manage_roles` pode criar e editar cargos inferiores respeitando a hierarquia, mas só pode conceder permissões que ele próprio possui efetivamente. A regra também se aplica a mudanças no JSONB: não é permitido conceder uma chave que o ator não possui, conceder `manage_roles` acima de sua autoridade ou contornar hierarquia por uma alteração de permissões. Os serviços de edição e atribuição validam as permissões efetivas antes/depois e a hierarquia dos membros ativos afetados. A exceção do proprietário não depende de suas permissões de cargo.

A validação calcula o conjunto efetivo do ator antes da escrita (união de `@everyone` e cargos individuais), identifica as permissões que passam a ser concedidas pela operação e compara esse delta ao conjunto do ator. Permissões removidas não são concessões, mas a remoção ainda exige `manage_roles`, validação de cargo/alvo e hierarquia. O cálculo deve abranger também os membros ativos já afetados pela edição de um cargo e impedir autopromoção ou escalada indireta. Nenhum identificador novo de permissão é criado por essa regra.

Todos os membros com participação `ACTIVE` podem visualizar os cargos do servidor. A consulta exige autenticação e participação ativa; membros `LEFT` não podem consultar. Essa leitura não concede autorização para criar, editar, atribuir ou excluir cargos. A API implementa `GET /servers/{server_id}/roles` e `GET /servers/{server_id}/roles/{role_id}`. A listagem usa `position` crescente, com `id` como desempate; a consulta individual exige que o cargo pertença ao servidor informado. Nenhuma das operações exige `manage_roles`.

O CRUD de cargos está implementado nos endpoints `POST /servers/{server_id}/roles`, `PATCH /servers/{server_id}/roles/{role_id}` e `DELETE /servers/{server_id}/roles/{role_id}`, além dos GET acima. Todos exigem JWT e participação `ACTIVE`; a identidade do ator vem do principal autenticado, e as regras de negócio ficam no serviço. Criação e edição aplicam autorização do proprietário ou `manage_roles` com hierarquia estrita para membros comuns, limite de concessão de permissões, validação do catálogo e posição >= 1. Criação não atribui o cargo e nome duplicado por igualdade exata retorna conflito. PATCH aceita apenas campos permitidos, preserva campos omitidos. Quando recebe `permissions`, substitui as permissões do catálogo e preserva chaves legadas. Cargos `is_system_role=True` não podem ser editados ou excluídos, inclusive pelo proprietário. Exclusão de cargo com qualquer associação em `ServerMemberRole` retorna `409 Conflict`, sem remover vínculos; sucesso retorna `204`. Edição e exclusão gravam auditoria transacional em `ServerConfigHistory`. Os endpoints `PUT /servers/{server_id}/members/{user_id}/roles/{role_id}` e `DELETE /servers/{server_id}/members/{user_id}/roles/{role_id}` atribuem e removem cargos individuais com validações de autorização, hierarquia, alvo ativo, servidor e concessão de permissões.

Para substituir permissões de um cargo ou de `@everyone`, o cliente envia `X-Expected-Permissions` com o objeto JSON de permissões conhecidas observado ao abrir a edição. Cada valor deve ser booleano; para a comparação, chave ausente equivale a `false`. O servidor compara essa base sob lock antes de gravar. Cabeçalho ausente resulta em HTTP 428, formato inválido em 422 e base desatualizada em 409 com `detail.code = permissions_conflict`. Um conflito rejeita todo o PATCH, inclusive os metadados enviados junto. O usuário pode carregar a configuração atual, revisar o rascunho e salvar novamente. A edição exclusiva de metadados dispensa o cabeçalho.

A exclusão de cargo exige autorização do proprietário ou `manage_roles`, além das validações de hierarquia aplicáveis e da proteção backend. Se o cargo ainda tiver atribuições individuais, retornar `409 Conflict`; não remover atribuições automaticamente nem alterar implicitamente permissões efetivas. Cargos com `is_system_role = true` não podem ser excluídos por nenhum ator.

## 4. Papel implícito `@everyone`

- Todo membro ativo possui implicitamente `@everyone`.
- Não é necessário criar um registro de `ServerMemberRole` para representar essa atribuição.
- `@everyone` representa permissões básicas aplicáveis a todos os membros ativos.
- O papel pode servir como alvo de menção coletiva, mas usar `@everyone` exige a permissão específica `mention_everyone`.
- A menção alcança somente membros ativos com acesso ao canal onde a mensagem foi enviada.
- O papel implícito não é um cargo individual atribuído, não altera a hierarquia e não deve ser confundido com `ServerRole.is_default`.
- As permissões básicas de `@everyone` são armazenadas em `Server.everyone_permissions`, JSONB próprio do servidor, com default `{}`, `NOT NULL` e constraint que exige objeto JSON. O modelo declara o campo e a revisão Alembic `8a62d13e4f90_add_server_permission_fields.py` o adiciona junto com `ServerRole.is_system_role`; essa revisão sucede `bc365585aa97`.
- A rota implementada `PATCH /servers/{server_id}/everyone-permissions` substitui integralmente o objeto: permissões omitidas deixam de ser concedidas e `{}` é válido. O schema aceita somente `kick_members`, `ban_members`, `unban_members`, `manage_invites`, `manage_roles` e `mention_everyone`, com booleanos estritos; chaves desconhecidas e valores que não sejam booleanos são rejeitados.
- A alteração exige autenticação, participação `ACTIVE` e que o usuário autenticado seja o proprietário real. `manage_roles` não concede essa autoridade. O serviço bloqueia o servidor com `SELECT FOR UPDATE`, registra `setting_name = "everyone_permissions"`, ator autenticado e valores anterior/novo em `ServerConfigHistory`, e atualiza configuração e histórico na mesma transação. Falha na auditoria reverte também a configuração. Os novos grants são observados imediatamente pelo resolvedor para membros ativos.
- `everyone_permissions` não concede acesso a canais privados. Esse campo não é usado como regra de autorização de canal; o serviço de canais verifica os cargos individuais autorizados.

## 5. Canais privados e acesso ao conteúdo

- A autorização para visualizar um canal é verificada separadamente das permissões gerais do servidor.
- O acesso a canal privado é concedido exclusivamente por cargos: o membro precisa possuir ao menos um dos cargos autorizados para o canal. Não há concessão individual direta a usuários.
- Um canal privado pode restringir um membro mesmo quando um de seus cargos concede visualização geral no servidor.
- A regra específica do canal prevalece para decidir se aquele membro pode visualizar/acessar o canal. Para conceder acesso, o membro precisa possuir ao menos um cargo individual explicitamente autorizado para o canal. `@everyone` nunca concede acesso a canal privado; permissões gerais armazenadas em `Server.everyone_permissions` não substituem essa regra. A união de permissões continua valendo entre os cargos individuais. O proprietário mantém acesso especial a todos os canais privados.
- Um membro sem acesso ao canal não pode consultar suas mensagens, enviar mensagens, listar seu conteúdo ou obter seus dados por outra rota da API.
- A API deve verificar acesso antes de serializar ou retornar o canal, mensagens, anexos, contagens, metadados ou resultados de busca associados.
- Operações no canal exigem também autorização específica para a ação — por exemplo, enviar uma mensagem requer acesso ao canal e permissão de envio.
- Regras de canal não podem ser aplicadas somente na interface.

ServerChannel registra visibilidade e somente leitura. ServerChannelRole associa canais privados aos cargos autorizados. Somente o proprietário pode configurar a associação entre canal privado e cargos autorizados; `manage_roles` não concede essa autoridade. Concessões e remoções exigem validação no backend, registro de auditoria e transação atômica. `@everyone` não pode ser associado como autorização de acesso.

O proprietário sempre pode visualizar e acessar todos os canais privados do próprio servidor, independentemente de cargos, permissões funcionais ou concessões específicas do canal. Essa exceção não se estende a administradores ou moderadores e continua sujeita à autenticação e à validação de que a operação se refere ao servidor correto.

## 6. Membros e ciclo de participação

- Somente membros `ACTIVE` têm permissões e acesso ao servidor.
- Ao sair, ser removido ou expulso, o membro deixa de acessar canais e executar operações do servidor.
- Ao sair voluntariamente, ser removido ou expulso, todos os cargos individuais do membro devem ser removidos, sem associação correspondente em `server_member_roles`.
- Uma nova tentativa de saída voluntária ou remoção administrativa de participação que já esteja `LEFT` deve retornar erro; essas operações não são idempotentes.
- A tabela atual tem unicidade em `(server_id, user_id)`. Reentrada deve reativar o registro existente em vez de inserir outra linha para o mesmo par.
- Na reativação, status e `left_at` devem voltar a representar participação ativa. `joined_at` deve ser atualizado para a data/hora da entrada mais recente e representa o início da participação atual. O membro não recupera cargos anteriores e recebe somente as permissões implícitas de `@everyone` até que novos cargos sejam atribuídos.
- Se futuramente for necessário preservar o histórico das atribuições de cargos, será preciso definir uma estratégia própria de auditoria ou histórico; não há estrutura existente aprovada para isso.
- A existência de um registro de membro, sem verificar seu status, nunca basta para autorizar a operação.

### 6.1 Saída voluntária e expulsão

- Qualquer membro pode sair voluntariamente quando quiser, exceto o proprietário atual, que deve transferir a propriedade antes. Saída e expulsão alteram participação para `LEFT`, preenchem `left_at` e removem todas as atribuições individuais de cargos; nenhuma cria banimento.
- `kick_members` permite expulsar outro membro `ACTIVE`. Membro não proprietário precisa da permissão e hierarquia estritamente superior ao alvo; mesma hierarquia não age entre si. O proprietário pode expulsar qualquer outro membro ativo sem permissão ou comparação hierárquica.
- Não é permitido expulsar a si mesmo nem o proprietário. Saída ou expulsão repetida de participação já `LEFT` retorna erro.
- A expulsão e seu evento `MEMBER_KICKED` em `ServerAuditLogs` são uma transação. A expulsão não impede retorno posterior mediante convite válido e demais condições.

### 6.2 Banimentos e revogações

- `ban_members` permite banir somente membro `ACTIVE`. Usuário `LEFT` ou que nunca participou não pode ser banido. Não é permitido autobanimento nem banir o proprietário.
- Membro não proprietário precisa de `ban_members` e hierarquia estritamente superior ao alvo. O proprietário pode banir qualquer outro membro ativo sem depender da permissão ou hierarquia.
- Banimento encerra participação como `LEFT`, preenche `left_at`, remove cargos individuais e registra banimento e evento `MEMBER_BANNED` em uma transação. Expulsão e saída voluntária não criam banimento.
- Cada novo ciclo gera novo registro. Banimentos permanecem ativos até revogação manual; não expiram e não são temporários. Banimento ativo bloqueia entrada mesmo com convite válido.
- `ServerBans` registra servidor, usuário, responsável, data/hora, motivo opcional, status ativo/revogado e dados de revogação. Também registra `target_highest_role_position`: maior posição dos cargos individuais do alvo no momento do banimento, ou `0` se não tiver cargos. `@everyone` não participa. O snapshot é capturado antes da limpeza das atribuições e deve ter valor mínimo `0`.
- `unban_members` permite revogar banimento ativo. O proprietário pode revogar qualquer banimento; outros membros precisam da permissão e hierarquia estritamente superior a `target_highest_role_position`. Membros de mesma hierarquia não podem revogar um ao outro.
- Revogar atualiza o ciclo existente como revogado, registra responsável e data/hora e cria evento `MEMBER_UNBANNED`, atomicamente. Não reativa a participação. O usuário pode tentar entrar depois por convite válido e demais condições.
- As estruturas `ServerBans` e `ServerAuditLogs` são separadas. Cada novo ciclo de banimento usa novo registro; o histórico dos ciclos e eventos anteriores permanece disponível.

### 6.3 Convites e entrada

- `manage_invites` permite criar e revogar convites. O proprietário pode criar e revogar sem a permissão; demais membros precisam estar ativos e possuir `manage_invites`.
- Tokens devem ser seguros e persistidos somente como hash. Validar hash, expiração, revogação e limite de usos.
- Qualquer usuário autenticado pode aceitar convite válido, desde que não tenha banimento ativo e cumpra as demais regras de entrada. Verificar banimento antes de consumir o convite.
- Participação e consumo do convite são atômicos. Para nova participação, criar `ACTIVE`; para participação existente `LEFT`, reutilizar a linha única, marcar `ACTIVE`, limpar `left_at`, atualizar `joined_at` e não restaurar cargos.
- Se o usuário já for `ACTIVE`, retornar `409 Conflict` sem consumir o convite nem alterar cargos, permissões, associação ou `joined_at`.
- Não criar endpoint de entrada que contorne o convite. Um banimento ativo impede reentrada; a revogação permite uma tentativa posterior com convite válido.

## 7. Menções coletivas

- Só quem possui `mention_everyone` pode enviar uma mensagem com `@everyone`.
- A menção alcança apenas membros ativos que podem visualizar o canal da mensagem.
- Não notificar nem revelar a existência de canal ou conteúdo privado a membros sem acesso.
- A autorização é feita no backend durante o envio e o cálculo dos destinatários; não confiar em destinatários fornecidos pelo cliente.

## 8. Verificações obrigatórias no backend

Antes de executar a operação, verificar identidade autenticada, servidor e objetos relacionados, status ativo, acesso ao canal quando aplicável, permissão funcional e hierarquia quando aplicável. Aplicar essas verificações a:

- criação e edição de servidores;
- criação, edição, exclusão, ordenação e configuração de canais;
- criação e edição de cargos, alteração de permissões, exclusão e atribuição/remoção de cargos;
- entrada, saída voluntária, expulsão, banimento, revogação e reativação de membros;
- criação, edição, exclusão e envio de mensagens em canais;
- consulta de canais privados, mensagens e demais conteúdos associados;
- transferência de propriedade;
- criação, validação, consumo e revogação de convites;
- expulsão, banimento, revogação e consulta de banimentos/auditoria;
- uso de `@everyone`.

O proprietário pode expulsar, banir e revogar sem as permissões funcionais correspondentes ou comparação hierárquica; pode criar/revogar convites sem `manage_invites`, consultar banimentos ativos e revogados e consultar toda a auditoria. Os demais precisam das permissões definidas nesta especificação. `kick_members` e `ban_members` não autorizam consulta de banimentos; `unban_members` autoriza consultar somente os ativos. A auditoria completa é exclusiva do proprietário. Falhas de autorização devem ocorrer antes de expor dados; IDs enviados pelo cliente nunca determinam associação, hierarquia ou permissão.

O proprietário ativo pode atribuir qualquer cargo comum do servidor a outro membro ativo do mesmo servidor ou a si próprio, mesmo quando não possui as permissões concedidas pelo cargo. Cargos de sistema continuam protegidos.

Para gestão de cargos, membro não proprietário também precisa limitar cada concessão ao conjunto de permissões efetivas que já possui. Essa verificação é feita no backend sobre o delta de concessões e as permissões efetivas dos alvos antes/depois da operação; não basta a posição do cargo nem uma validação da interface.

As consultas de membros, banimentos e auditoria são paginadas com `limit=20` e máximo `100`. Membros ativos são ordenados por `joined_at` decrescente, com desempate estável por ID. Banimentos e auditoria são ordenados cronologicamente em ordem decrescente. A rota de banimentos oferece paginação: o proprietário inclui ciclos ativos e revogados e membros com `unban_members` recebem somente ativos. A auditoria aceita filtros por tipo de evento, ator e alvo. Filtros por período/status não são parâmetros HTTP atualmente implementados.

## 9. Auditoria e transações

- Alterações de configuração do servidor devem gerar registro em `server_config_history` com servidor, ator, nome da configuração, valor anterior, valor novo e horário.
- A atualização e o respectivo registro de histórico são uma única unidade transacional.
- Transferência de propriedade grava `owner_id` em `ServerConfigHistory` e também gera `OWNERSHIP_TRANSFERRED` em `ServerAuditLogs`; ambos são atômicos com a atualização do servidor. O primeiro registra a alteração de configuração; o segundo registra o evento de negócio.
- A tabela atual não impõe que o autor do histórico esteja autorizado. Essa validação é responsabilidade do serviço.
- `ServerAuditLog` é separada de `ServerBan`. A regra de negócio aprovada prevê eventos de moderação e, em etapa futura, `OWNERSHIP_TRANSFERRED`; a implementação atual registra `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED`. Cada evento de moderação contém servidor, ator, alvo, tipo, data/hora e justificativa opcional; banimento/revogação referenciam o ciclo aplicável.
- Concessões e remoções de acesso de cargos a canais privados também são eventos auditáveis em `ServerAuditLogs` (conceitualmente `CHANNEL_ROLE_ACCESS_GRANTED` e `CHANNEL_ROLE_ACCESS_REVOKED`), registrados na mesma transação da alteração. Alterações de `Server.everyone_permissions` são registradas em `ServerConfigHistory`, com valores anterior/novo, também atomicamente com a configuração.
- Eventos são preservados sem expiração automática, mesmo após reentrada ou revogação. Ações e logs correspondentes são gravados na mesma transação. Identificadores históricos são preservados; em exclusão de conta, dados pessoais podem ser anonimizados quando necessário.
- FKs e regras `ON DELETE` devem impedir órfãos e exclusão automática de registros históricos. A política técnica deve permitir anonimização preservando os identificadores referenciados, em vez de apagar cascata.
- A edição e a exclusão de cargos registram em `ServerConfigHistory` snapshots JSON do estado alterado/anterior, com ator, servidor e chave `server_role:<id>`, na mesma transação da mutação. A exclusão guarda o snapshot completo do cargo e `{"deleted": true}` como novo valor. A política de auditoria para atribuição/remoção manual de cargos continua pendente; concessões e remoções de acesso de cargo a canal privado exigirão auditoria. Alterações de configuração do servidor, incluindo `everyone_permissions`, também usam `ServerConfigHistory`.

O endpoint de alteração de `everyone_permissions` já obedece a essas exclusividades. A futura configuração de cargos com acesso a canais privados também será exclusiva do proprietário. `manage_roles` não substitui a autoridade do proprietário em nenhuma das duas operações.

## 10. Estrutura existente e lacunas de implementação

Os modelos atuais relacionados são `Server`, `ServerMember`, `ServerChannel`, `ServerRole`, `ServerMemberRole`, `ServerInvite`, `ServerConfigHistory`, `ServerBan` e `ServerAuditLog`. Eles estão registrados em `app/models/__init__.py`; a revisão `8a62d13e4f90_add_server_permission_fields.py` acrescenta `Server.everyone_permissions`, sua constraint de objeto JSON e `ServerRole.is_system_role`, e `d8f4c2b19a70` cria as estruturas de banimento e auditoria de moderação.

O schema oferece `owner_id`; status e unicidade de membro; cargos e associação múltipla com FKs compostas; `everyone_permissions` JSONB; configurações do servidor; convites com hash, limite de usos, expiração e revogação; histórico de configuração; e estruturas próprias `ServerBan` e `ServerAuditLog`. A transferência de propriedade ainda não possui fluxo implementado.

`ServerRole.position` é inteiro não nulo, sem default Python ou de banco, e a constraint `ck_server_roles_position_positive` impõe `position >= 1`; posições iguais são permitidas. `get_member_hierarchy_level` calcula a maior posição dos cargos individuais, ignorando `@everyone`, e `is_hierarchy_comparison_approved` valida ator/alvo `ACTIVE`, exige posição estritamente superior para membros comuns e mantém separada a autoridade especial do proprietário. A comparação não substitui a permissão específica. Os serviços de cargos, atribuições e moderação aplicam as verificações de autorização/hierarquia de cada operação. `is_system_role`, independente de `is_default`, protege cargos marcados contra edição e exclusão, inclusive pelo proprietário; a lista e o mapeamento dos cargos reservados continuam pendentes.

O CRUD básico de servidores e o núcleo de participação (consulta de membros ativos e saída voluntária) têm rotas, schemas, serviços e testes. A resolução central de permissões, configuração owner-only de `everyone_permissions`, CRUD de cargos e atribuição/remoção manual também estão implementados. A comparação hierárquica não concede permissão funcional; os serviços de cargos e moderação fazem as validações pertinentes. Os modelos `ServerBan` e `ServerAuditLog`, a migration `d8f4c2b19a70`, os serviços e rotas de kick/ban/unban, lista de banimentos e auditoria estão no código. Kick/ban/unban preservam as regras aprovadas e a auditoria de eventos `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED`; unban não reativa participação nem restaura cargos. Criação, listagem, aceitação e revogação de convites também estão implementadas, com reentrada transacional e bloqueio de entrada para banimento ativo. A transferência de propriedade e os canais privados estão implementados. As mensagens usam uma Conversation do tipo CHANNEL ligada ao canal.

O módulo de denúncias e moderação oficial é separado desta especificação de autorização de servidores e também está implementado no código: `POST /reports` persiste denúncia/evidência; as rotas `/official/reports` exigem equipe oficial ativa e não revogada, oferecendo fila, detalhe, análise, triagem e decisão humana. A triagem humana é condição necessária para a análise externa; suspeita de exploração sexual infantil registrada com justificativa mantém o caso em revisão humana e bloqueia o envio à OpenAI. O worker persistente usa tentativas, lease, recuperação e controle de concorrência; análise elegível usa `omni-moderation-latest`, sem punição automática, e a decisão final é humana. A integração real em duas denúncias de exemplo foi reportada como validada anteriormente; essa evidência não foi consultada nesta atualização. A validação recente reportada inclui 32 testes backend dos módulos de análise/API oficial, mas não representa uma execução completa da suíte. A última suíte completa conhecida continua sendo o resultado histórico `464 passed, 0 failed, 0 skipped`, não repetido nesta atualização.

### Rotas HTTP de moderação e convites implementadas

- Moderação: `POST /servers/{server_id}/members/{user_id}/kick`, `POST /servers/{server_id}/members/{user_id}/ban`, `GET /servers/{server_id}/bans`, `POST /servers/{server_id}/bans/{ban_id}/unban` e `GET /servers/{server_id}/audit-logs`. Todas exigem JWT e usam `current_user.id`; os serviços fazem a autorização, hierarquia e persistência. A lista de banimentos é paginada; auditoria é paginada e aceita filtros por tipo, ator e alvo. Respostas públicas não incluem snapshot interno de cargos.
- Convites: `POST /servers/{server_id}/invites`, `POST /servers/{server_id}/invites/accept`, `GET /servers/{server_id}/invites` e `DELETE /servers/{server_id}/invites/{invite_id}`. Todas exigem JWT. Criação/listagem/revogação exigem proprietário ou `manage_invites`; aceitação usa o usuário autenticado. O token original é retornado somente na criação; listagem e respostas não expõem hash.
- `server_invite_service.py` gera token criptograficamente seguro, persiste somente SHA-256, valida expiração/revogação/usos e consome o convite na mesma transação da criação/reativação da participação. Banimento ativo bloqueia a entrada sem consumir o convite; reentrada atualiza `joined_at` e não restaura cargos.
- `server_moderation_service.py` implementa kick, ban, unban e consultas, com alterações de estado e eventos de moderação na mesma transação.

### 10.1 Investigação técnica de `ServerRole.is_default`

**Uso encontrado no código:** `app/models/server_role.py` declara `is_default` como booleano não nulo, com default Python `False`. O modelo também declara o índice único parcial `uq_server_roles_one_default`, que permite no máximo um cargo com `is_default = true` por servidor. A migration `457fe8255da3` cria a coluna não nula e o mesmo índice parcial; não define default no banco. O downgrade remove índice e tabela.

O schema de resposta da leitura de cargos expõe `is_default` como campo de dados do modelo. Não há lógica de serviço ou rota que use seu valor para autorização, atribuição, hierarquia ou proteção, e os testes de leitura apenas verificam que ele permanece independente de `is_system_role`. Portanto, não foi encontrada regra funcional da API que dependa do marcador. O índice constitui a semântica física observável: no máximo um registro por servidor pode ser marcado como default; ele não exige que exista algum. Não há constraint que associe esse marcador a nome, posição, permissões, atribuições ou proteção contra alteração. O preflight autorizado de leitura do banco de desenvolvimento registrou zero cargos com `is_default = true`.

Para auditoria futura, esta consulta somente de leitura reproduz a verificação de cargos `is_default`; o preflight autorizado encontrou zero resultados:

```sql
SELECT id, server_id, name, position, is_default
FROM server_roles
WHERE is_default IS TRUE
ORDER BY server_id, id;
```

Alternativas para aprovação:

1. **Preservar a estrutura e a função técnica atual:** manter coluna e índice como estão, sem tratá-los como `@everyone` e sem atribuir novas regras de autorização. Vantagem: nenhuma alteração ou risco de compatibilidade; preserva registros e deixa o marcador disponível. Desvantagem: finalidade não documentada continua no schema e consumidores futuros podem interpretar “default” de formas diferentes. Impacto no código e banco: nenhum imediato.
2. **Adaptar a uma finalidade distinta e aprovada:** por exemplo, identificar um cargo individual padrão para novos membros. Essa finalidade não deve ser escolhida por inferência e exigiria decisão explícita sobre criação, atribuição e hierarquia. Cargos reservados ao sistema agora têm representação própria aprovada em `is_system_role`; não se deve reutilizar `is_default` para essa função. Vantagem: aproveita o campo/índice existente para uma eventual finalidade de cargo padrão individual. Desvantagem: o nome atual não expressa necessariamente essa finalidade, e a unicidade de um por servidor pode não representar as regras futuras. Impacto: validações em serviço/API, possíveis ajustes de schema/índice e testes; compatibilidade dependerá dos valores existentes.
3. **Remover em migration futura:** remover coluna e índice após busca de consumidores e inspeção dos dados. Vantagem: elimina estado sem uso encontrado e reduz ambiguidade. Desvantagem: perde qualquer classificação existente e quebra código externo ou consultas que leiam o campo. Impacto: migration destrutiva, alteração do modelo e qualquer integração que dependa da coluna; requer plano de reversão/compatibilidade e inspeção prévia de `is_default = true`.

**Decisão atual:** preservar temporariamente a coluna e o índice sem lhes atribuir significado de produto ou relação com `@everyone` ou `is_system_role`. A finalidade futura de `is_default` continua pendente e depende de justificativa funcional e consulta dos registros existentes em ambiente autorizado. Não remover nem reinterpretar o campo nesta etapa.

## 11. Decisões aprovadas, detalhes técnicos e pendências

### Decisões de negócio aprovadas

- Permissões independentes: `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles`; hierarquia e exceções do proprietário conforme seções 3 e 6.
- Configuração de permissões gerais: somente o proprietário altera `Server.everyone_permissions`; a alteração é validada no backend, registrada em `ServerConfigHistory`, transacional e efetiva imediatamente para membros ativos. `manage_roles` não concede essa autoridade. A rota de substituição integral, com validação do catálogo e booleans estritos, está implementada.
- Configuração de acesso privado: somente o proprietário define cargos autorizados por canal; `manage_roles` não concede essa autoridade. `@everyone` não autoriza acesso; concessões/remoções são auditadas e transacionais, preservando o acesso especial do proprietário.
- Limite de concessão de cargos: proprietário pode configurar todas as permissões aprovadas em cargos comuns; membro com `manage_roles` só concede capacidades que já possui efetivamente e não pode usar atribuição ou JSONB para elevar a si ou a alvos acima da própria autoridade. Cargos `is_system_role` não podem ser modificados nem pelo proprietário.
- Visualização de cargos: todos os membros `ACTIVE` autenticados podem consultar os cargos; a leitura não concede permissão de mutação.
- Cargos reservados: usar campo próprio `is_system_role`, separado de `is_default`; cargos marcados não podem ser excluídos nem ter propriedades estruturais modificadas por ninguém, inclusive pelo proprietário. A identificação não depende de nome ou posição.
- Exclusão de cargos: retornar `409 Conflict` se houver atribuições individuais; não limpar atribuições como efeito colateral nem alterar implicitamente permissões dos membros.
- Canais privados nunca concedem acesso por `@everyone`; acesso requer cargo individual autorizado, e o proprietário conserva acesso especial.
- Banimento somente de membro `ACTIVE`, sem autoação; cada ciclo registra snapshot `target_highest_role_position`, e ciclos anteriores permanecem preservados.
- Acesso a banimentos: proprietário vê ativos e revogados; `unban_members` vê somente ativos; auditoria completa é exclusiva do proprietário.
- Aceitar convite com participação já `ACTIVE` resulta em `409 Conflict`, sem consumo ou alteração de estado.
- Paginação padrão 20, máximo 100; ordenação por data decrescente conforme seção 8.
- Eventos auditados: `MEMBER_KICKED`, `MEMBER_BANNED`, `MEMBER_UNBANNED`, `OWNERSHIP_TRANSFERRED` e concessão/revogação de acesso de cargo a canal privado (tipos conceituais `CHANNEL_ROLE_ACCESS_GRANTED` e `CHANNEL_ROLE_ACCESS_REVOKED`). Auditoria sem expiração automática, IDs históricos preservados e anonimização pessoal permitida quando necessária.
- Cargos individuais têm `position >= 1`; a constraint `ck_server_roles_position_positive` está no modelo e na migration `990fa9af113d`. Não há default Python ou de banco, e posições iguais continuam permitidas. O cálculo do nível hierárquico efetivo e a comparação central estão implementados: considera-se a maior posição individual, `@everyone` é ignorado e membro sem cargo individual tem nível 0. Criação/edição/exclusão e atribuição/remoção de cargos, além de kick/ban/unban, aplicam autorização e comparação hierárquica nos serviços. A comparação não substitui a permissão funcional exigida.
- Transferência de propriedade aceita qualquer membro ativo e não banido, sem requisito de cargo; as autoridades especiais mudam imediatamente e o evento é registrado.
- Convite aceito por usuário que já é `ACTIVE` resulta em `409 Conflict`, sem consumo nem alterações de estado.
- Exclusão automática por prazo não se aplica à auditoria; IDs históricos permanecem e dados pessoais podem ser anonimizados sem apagar as referências.

### Detalhes técnicos a definir durante a implementação

- Detalhes técnicos de futuras estruturas de transferência e canais privados, conforme convenções do repositório; `ServerBan` e `ServerAuditLog` já estão modelados e incluídos em migration no código.
- Recomenda-se persistir `target_highest_role_position` como inteiro não nulo com `CHECK >= 0`; o valor `0` representa alvo sem cargos individuais no momento do banimento.
- Estratégia concreta de FKs e `ON DELETE` que preserve histórico, evite órfãos e permita anonimização mantendo IDs.
- Algoritmo criptográfico para hash dos tokens de convite, mantendo token aleatório de alta entropia e sem armazenamento do valor bruto.
- Estratégia de locks e ordem de aquisição para serializar entrada, convite, banimento, transferência e saída.
- Filtros de período/estado nos endpoints conforme os campos disponíveis, dentro dos limites e permissões já aprovados.
- Não há backfill de `position` pendente: o preflight autorizado encontrou zero posições inválidas. Se dados legados inválidos forem encontrados em outro ambiente, qualquer correção exigirá nova análise e aprovação, sem heurística automática.
- Escolha dos tipos exatos de status/ação, names físicos e estratégia de índices dentro das recomendações e regras aprovadas.

### Questões de negócio ainda pendentes

1. Catálogo e semântica de permissões além das aprovadas, incluindo permissões futuras de canais e mensagens.
2. Significado/finalidade operacional futura de `ServerRole.is_default`.
3. Identificação exata dos cargos que terão `is_system_role = true` e mapeamento dos cargos existentes para essa classificação antes da migration. O uso de `is_system_role` como campo está aprovado; a lista concreta permanece pendente.
4. Detalhamento dos limites para permissões funcionais em JSONB além do teto de concessão por membro comum já aprovado; essa pendência não reabre o limite aprovado de que membros comuns só concedam permissões efetivas que já possuem.
5. Política HTTP exata para ocultar recursos privados, mantendo a regra de não revelar recursos a quem não tem acesso.
6. Eventos adicionais de auditoria além dos eventos já aprovados, especialmente para atribuições de cargos, sem retirar a auditoria obrigatória de acesso a canais privados.
7. Ciclo de vida de servidor e canal (exclusão/arquivamento e dependências), sem afetar a preservação histórica aprovada.
8. Verificação documental futura, caso seja aprovada. A política atual usa autodeclaração conforme docs/regras-idade.md.

## 12. Critérios de teste para a futura implementação

- Proprietário criado como `owner_id` e membro ativo; nenhum cliente consegue escolher outro proprietário.
- Um membro ou moderador comum não remove nem altera a autoridade do proprietário; proprietário não sai sem transferência para membro elegível ativo.
- Transferência atualiza proprietário e auditoria atomicamente; falha em qualquer gravação não deixa estado parcial.
- Cargo de posição igual/superior não pode ser gerenciado pelo ator; cargo atribuído não pode exceder o nível permitido; posição sozinha não concede permissão funcional.
- `manage_roles` é independente; sem ela, o membro comum não gerencia cargos mesmo que tenha outras permissões administrativas. Atribuição/remoção respeita posição do cargo e hierarquia do alvo; cargos marcados `is_system_role` são imutáveis para qualquer ator, inclusive o proprietário, que pode gerenciar os demais cargos comuns.
- Todos os membros `ACTIVE` autenticados podem listar/consultar cargos; membros `LEFT` não podem. Essa visualização não concede capacidade de mutação.
- Cargo marcado `is_system_role` não pode ser excluído nem ter propriedades estruturais modificadas por membro comum ou proprietário; `is_default` não substitui esse marcador.
- Excluir cargo ainda atribuído retorna `409 Conflict` e não apaga associações nem altera permissões efetivas de membros.
- Membro comum não consegue conceder permissão que não possui efetivamente; mudanças JSONB são avaliadas pelo delta e permissões efetivas de ator/alvos antes/depois. Permissões removidas não contornam os requisitos de `manage_roles`, posição, alvo e autorização backend.
- Para membro com vários cargos, a maior `position` determina a hierarquia; `@everyone` fica fora do cálculo; membro sem cargo individual tem nível 0 e cargos individuais devem ter `position >= 1`.
- Permissão concedida por qualquer cargo prevalece sobre ausência em outros; múltiplos cargos não criam duplicatas; membro novo não recebe cargo individual automaticamente.
- `@everyone` é efetivo sem linha individual em `server_member_roles`; menção exige `mention_everyone` e só alcança membros ativos com acesso ao canal.
- Permissões gerais de `@everyone` vêm da configuração própria do servidor e se unem às permissões dos cargos, mas nunca concedem acesso a canais privados; o canal exige cargo individual autorizado e o proprietário mantém acesso especial.
- Membro sem acesso a canal privado não obtém canal, mensagens ou metadados por endpoints alternativos, mesmo conhecendo os IDs; membro `LEFT` também não acessa.
- Proprietário acessa canais privados do próprio servidor independentemente de cargos ou permissões; essa exceção não vale automaticamente para moderadores ou administradores.
- Reentrada reativa o registro único de membro, sem inserir uma segunda linha.
- Reentrada atualiza `joined_at` para a entrada mais recente, não restaura cargos antigos e exige ausência de banimento ativo e convite válido.
- Saída voluntária e expulsão removem as associações de cargos e deixam a participação `LEFT`; nenhuma cria banimento. Expulsão não proprietária exige `kick_members` e hierarquia superior; proprietário pode expulsar membro ativo sem permissão/hierarquia. Expulsão permite retorno posterior com convite válido.
- Saída voluntária ou expulsão repetida de participação `LEFT` retorna erro; saída voluntária não cria banimento.
- `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles` são independentes: possuir uma não concede as outras. Outras permissões administrativas não concedem essas capacidades implicitamente.
- Gestão de cargos por membro comum exige `manage_roles`, cargo estritamente abaixo da maior posição individual do ator, respeito à hierarquia do alvo e bloqueio de cargos `is_system_role`; o proprietário pode gerenciar cargos comuns, mas não cargos reservados.
- Banimento e encerramento da participação/remoção de cargos são atômicos; status `LEFT` sozinho não representa banimento.
- Banimento ativo impede entrada mesmo com convite válido; revogação permite entrada futura mediante convite válido.
- Banir exige alvo `ACTIVE`, impede auto/owner-ban, exige `ban_members` e hierarquia superior para não proprietários; proprietário pode banir qualquer alvo ativo sem permissão/hierarquia. Snapshot `target_highest_role_position` é capturado antes da remoção de cargos. Revogar exige `unban_members` e superioridade sobre o snapshot, exceto proprietário, que pode revogar qualquer banimento.
- Banimentos não expiram automaticamente; permanecem até revogação manual. Saída voluntária não cria banimento.
- `ServerBan` e `ServerAuditLog` são estruturas separadas. A implementação atual registra `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED`, preservados após retorno ou revogação. `OWNERSHIP_TRANSFERRED` permanece previsto, mas depende da futura transferência de propriedade. Os eventos de moderação não têm expiração automática.
- Proprietário não pode ser removido ou banido por outro membro nem sair antes da transferência de propriedade.
- Consulta de banimentos: proprietário recebe ciclos ativos e revogados; membro com `unban_members` somente ativos; `kick_members`/`ban_members` isolados não dão acesso. Auditoria completa só para proprietário.
- Aceitar convite por membro já ativo responde `409` e não consome o token nem altera cargo, permissão ou timestamps; banimento ativo é verificado antes do consumo.
- Expulsão verifica `kick_members` e hierarquia superior para atores não proprietários; banimento e revogação verificam `ban_members`/`unban_members` e hierarquia, aplicando a exceção do proprietário.
- Listas de membros, bans e logs respeitam paginação padrão 20/máximo 100 e ordenação decrescente definida; filtros autorizados por estado/período e tipo retornam apenas dados permitidos.
- Eventos de expulsão, banimento e revogação são registrados em `ServerAuditLogs` com os campos aprovados e permanecem após reentrada ou revogação; eventos e alterações de estado são transacionais.
- Transferência de propriedade pode ser feita pelo proprietário atual a qualquer membro ativo e não banido do mesmo servidor, sem exigir cargo administrativo; as autoridades especiais mudam imediatamente e a alteração de propriedade e auditoria são atômicas.
- Associação de cargo e membro de outro servidor é rejeitada pela integridade referencial; além disso, o ator precisa estar autorizado a fazer a atribuição.
- Toda autorização é exercitada em chamadas de API; testes não devem validar apenas funções isoladas ou regras da interface.


## Contrato de mensagens de canal

Todos os caminhos abaixo têm prefixo `/servers/{server_id}/channels/{channel_id}` e exigem JWT, participação ACTIVE e acesso atual ao canal. A ausência de acesso ao recurso produz 404. A identidade do autor vem do JWT.

| Método e caminho | Contrato |
| --- | --- |
| GET /messages | Janela mais recente em ordem cronológica. `limit` de 1 a 100 (padrão 50). `before_id` ou `after_id` exclusivos e pertencentes ao canal. Retorna items, has_more, updates_revision e can_publish. |
| GET /message-updates | Recebe after_revision e limit. Retorna eventos CREATED, UPDATED ou DELETED, com event_revision, message_state_revision e estado atual. Continuar por next_cursor enquanto has_more. |
| POST /messages | Recebe content (1 a 5.000 caracteres, com normalização). Retorna 201, message e message_state_revision. |
| PATCH /messages/{id} | Mesmo corpo, somente autor autorizado a publicar, até 15 minutos pelo relógio do banco. Conteúdo idêntico não produz nova revisão. |
| DELETE /messages/{id} | Exclusão lógica pelo autor com acesso, mesmo em somente leitura. Retorna 200 com representação ocultada; repetição autorizada mantém a revisão. |
| POST /messages/{id}/reports | Recebe reason (1 a 500 caracteres). Retorna 201. Exige mensagem visível de outro autor. Duplicata do mesmo denunciante retorna 409. |

Membros ativos com acesso publicam nos canais TEXT comuns. Somente o proprietário ativo publica em canais somente leitura ou em canais VOICE (mensagem de texto, sem áudio). Cargos administrativos não concedem exceção. Apenas o proprietário configura `is_read_only` por POST/PATCH de canal. A mudança é auditada. Canais privados continuam exigindo cargo individual autorizado ou propriedade.

A configuração `PATCH /servers/{server_id}` com `ai_moderation_enabled` exige proprietário e gera histórico. A denúncia preserva os IDs de servidor, canal, mensagem e autor, conteúdo e timestamps originais. Somente a triagem oficial torna o trabalho elegível; a configuração de IA do servidor é verificada também na reivindicação do trabalho. A decisão de sancionar permanece humana.


## Política etária adicional

A autoridade especial do proprietário e as permissões de cargos não dispensam idade mínima de 18 anos para servidores +18. A classificação is_adult é definida na criação e rejeitada em PATCH. A elegibilidade é calculada no backend em cada acesso. Contas sem data válida ficam sem acesso a servidores +18. Retornar 404 evita confirmar a existência do servidor. A declaração de nascimento não concede participação, acesso privado ou qualquer permissão adicional. Ver `docs/regras-idade.md`.
