# Contexto do TCC

## Identificação e objetivo

**Título provisório:** Desenvolvimento de uma Plataforma de Comunicação Segura com Mecanismos Inteligentes de Moderação e Proteção de Usuários.

O objetivo é desenvolver uma plataforma de comunicação com foco em segurança, privacidade, comunidades e moderação inteligente. A proposta não é simplesmente clonar o Discord.

Este documento registra decisões de negócio e direção do produto; não afirma que os requisitos já estejam implementados. Para o estado real do código e da API, consulte [STATUS_PROJETO.md](STATUS_PROJETO.md).

## Arquitetura e ambiente

### Backend e infraestrutura

- Python e FastAPI.
- PostgreSQL 17.
- SQLAlchemy como ORM e Alembic para migrações.
- Psycopg como driver PostgreSQL.
- JWT para autenticação e Argon2 para hash de senhas.
- Docker Compose atualmente define o serviço PostgreSQL. O container local chama-se `tcc-postgres` e publica a porta 5433 no host.
- Desenvolvimento em Windows 11, com VS Code e ambiente virtual Python.

### Frontend

O repositório contém uma aplicação web em `frontend/`, separada da API, construída com React, Vite, TypeScript, Tailwind CSS, React Router e Axios. Ela oferece cadastro, login e sessão JWT, painel autenticado, conversas e mensagens privadas e uma área de moderação oficial. A interface consome a API existente; a autorização efetiva continua no backend. O estado e as limitações observadas estão em [STATUS_PROJETO.md](STATUS_PROJETO.md).

### Organização atual do backend

- `app/main.py`: inicialização FastAPI, inclusão das rotas e verificações de saúde.
- `app/settings.py` e `app/database.py`: configuração e acesso ao PostgreSQL.
- `app/auth.py`: dependência de autenticação JWT.
- `app/schemas.py`: schemas Pydantic.
- `app/models/`: modelos SQLAlchemy.
- `app/routers/`: endpoints de usuários, conversas, mensagens, servidores, membros, cargos, convites, moderação de servidores, denúncias e moderação oficial.
- `app/services/`: serviços de conversas e mensagens, servidores, membros, cargos, autorização, convites, moderação de servidores e processamento/revisão de denúncias.
- `migrations/`: configuração e revisões Alembic.
- `frontend/`: aplicação React/Vite/TypeScript, cliente Axios, autenticação e telas de conversas e moderação.
- `docs/especificacao-tecnica.md`: especificação anterior, que pode divergir do código; confirme sempre contra o código e o status atual.

## Decisões de negócio estabelecidas

### Usuários, autenticação e privacidade

- Cadastro com nome de usuário único, e-mail e senha armazenada com hash seguro.
- Verificação de conta e autenticação em dois fatores estão previstas.
- O usuário pode bloquear outras pessoas.
- Preferências de privacidade devem controlar mensagens de desconhecidos, solicitações de amizade, convites para grupos e visibilidade do status online.
- Bloquear alguém não apaga as mensagens anteriores. Enquanto houver bloqueio em qualquer direção, os usuários não podem iniciar uma conversa direta, enviar mensagens nem consultar o histórico. Ao tentar reativar uma participação `LEFT`, o sistema verifica primeiro bloqueio e privacidade; se a tentativa for bloqueada, a participação continua `LEFT` e o histórico não pode ser recuperado. Sem bloqueio e com amizade aceita ou permissão do destinatário para mensagens de desconhecidos, o usuário pode reativar somente a própria participação, preservando as mensagens anteriores.
- Cada usuário pode ocultar a própria conversa independentemente, sem apagar o histórico dos demais.

### Amizades e conversas

- Haverá conversas individuais e em grupo.
- Amigos podem conversar normalmente.
- Não amigos só podem iniciar conversas individuais se o destinatário permitir mensagens de desconhecidos.
- Qualquer usuário pode criar grupos.
- Pessoas que não são amigas precisam aceitar um convite para entrar em grupos.
- O criador começa como administrador. Administradores podem gerenciar participantes, nome, imagem e outros administradores.
- Participantes comuns podem enviar mensagens e sair.
- O criador só pode sair depois de transferir a administração.

### Mensagens

- Edição dentro de 15 minutos; exclusão para todos dentro de 15 minutos, sujeita a autoria e permissões.
- Exclusão individual sem limite de tempo. Preservar histórico de edições e registros de exclusão.
- Texto, arquivos, imagens, vídeos, documentos e mensagens de voz estão previstos.
- Respostas, reações e encaminhamento estão previstos. Conteúdo encaminhado deve ser identificado como encaminhado.
- Não implementar indicadores de entrega ou leitura.
- Conversas individuais podem ser ocultadas sem apagar o histórico.
- Mensagens de grupos devem ser organizadas cronologicamente; respostas encadeadas podem se vincular à mensagem original.

### Servidores e comunidades

- Servidores são centrais à experiência e podem ter canais de texto e voz.
- Servidores podem ser classificados como +18. Acesso a servidores +18 exige verificação de idade; não armazenar documentos de identidade brutos.
- Inicialmente, servidores não são publicamente descobertos; o acesso ocorre por convite.
- O criador torna-se proprietário e deve ter participação ativa no servidor. O proprietário tem autoridade administrativa especial, independente de cargos; outros membros, inclusive moderadores, não podem removê-lo, bani-lo nem retirar essa autoridade.
- O proprietário só pode sair após transferir a propriedade a outro membro `ACTIVE` e não banido do mesmo servidor, sem exigir cargo administrativo. As autoridades especiais passam imediatamente ao novo proprietário; a transferência é auditada atomicamente como `OWNERSHIP_TRANSFERRED`.
- Membros podem ter vários cargos. Novos membros não recebem cargos individuais automaticamente. Todo membro ativo possui implicitamente `@everyone`, sem atribuição individual em `server_member_roles`.
- Para membros com vários cargos, a maior `position` entre os cargos individuais determina a hierarquia efetiva. Cargos com posição maior têm hierarquia superior; posições iguais representam o mesmo nível; membros sem cargos individuais têm nível 0, e `@everyone` não participa do cálculo. Cargos individuais devem ter `position >= 1`. O modelo não define default Python nem default no banco para `position`; a constraint `ck_server_roles_position_positive` impõe esse limite, e posições iguais são permitidas. A migration `990fa9af113d`, encadeada após `8a62d13e4f90`, foi validada em PostgreSQL descartável com upgrade e downgrade; nenhuma migration foi aplicada aos bancos de desenvolvimento ou testes. Posição não concede automaticamente permissões funcionais. Membros comuns precisam de `manage_roles` e só podem modificar cargos abaixo de sua maior posição individual; não podem promover a si ou a outros acima de sua autoridade, alterar cargos de posição igual/superior ou cargos reservados ao sistema. Ao alterar cargos de outro membro, a hierarquia do alvo também deve ser respeitada. O proprietário pode gerenciar cargos comuns e configurar todas as permissões aprovadas desses cargos. Cargos marcados `is_system_role` são protegidos contra exclusão e alteração estrutural por qualquer membro, inclusive o proprietário; essa proteção é validada no backend e não depende do nome ou da posição.
- A API implementa o CRUD de cargos: `GET /servers/{server_id}/roles`, `GET /servers/{server_id}/roles/{role_id}`, `POST /servers/{server_id}/roles`, `PATCH /servers/{server_id}/roles/{role_id}` e `DELETE /servers/{server_id}/roles/{role_id}`. Todas exigem JWT e participação `ACTIVE`; leitura não exige `manage_roles`, limita a consulta ao servidor informado e ordena a listagem por `position` crescente e `id` como desempate. Criação, edição e exclusão são autorizadas no serviço: proprietário tem autoridade especial para cargos comuns; membros comuns precisam de `manage_roles` e hierarquia estritamente superior à posição do cargo ou à posição solicitada.
- Os schemas de criação e edição rejeitam campos extras/internos, posição não inteira ou menor que 1, nomes inválidos e permissões fora das seis chaves aprovadas ou com valores não booleanos estritos. Nome duplicado por igualdade exata retorna conflito. Criação não atribui o cargo automaticamente. A edição substitui o objeto inteiro de permissões quando `permissions` é enviado; `false` não revoga grants de `@everyone` ou de outros cargos. Membros comuns só podem conceder permissões que já possuem efetivamente e não podem escalar a própria autoridade ou a de alvos ativos.
- Cargos com `is_system_role=True` não podem ser editados nem excluídos, inclusive pelo proprietário. `is_system_role` permanece independente de `is_default`; nenhum deles representa `@everyone`. A lista e o mapeamento dos cargos que serão reservados ao sistema continuam pendentes. Cargos atribuídos a qualquer membro não podem ser excluídos: a API retorna `409` e não remove atribuições. A edição e a exclusão registram snapshots em `ServerConfigHistory` na mesma transação da alteração; a exclusão guarda os dados anteriores e o marcador `deleted`.
- A atribuição e remoção manual de cargos individuais estão implementadas por endpoints e serviços. `ServerMemberRole` armazena associações com unicidade por membro/cargo e FKs compostas para o mesmo servidor; a saída voluntária, expulsão e banimento removem as associações no fluxo transacional correspondente. Edição e atribuição validam hierarquia e efeitos de permissões nos membros afetados.
- As permissões dos cargos são combinadas por união: uma concessão em qualquer cargo vale, e a ausência da permissão em outro cargo não a anula. Não usar negações entre cargos para contradizer essa regra.
- As permissões básicas de `@everyone` ficam em `Server.everyone_permissions`, campo JSONB próprio do servidor, são recebidas implicitamente por membros ativos e são combinadas por união com as permissões dos cargos. `@everyone` não é cargo individual; `mention_everyone` controla a menção coletiva. O campo e sua constraint de objeto JSON estão no modelo e na revisão Alembic `8a62d13e4f90_add_server_permission_fields.py`. A API implementa `PATCH /servers/{server_id}/everyone-permissions`: o proprietário ativo substitui integralmente a configuração; `manage_roles` não concede essa autoridade. O backend aceita somente as seis permissões documentadas, exige valores booleanos estritos, rejeita chaves desconhecidas, registra valores anterior/novo em `ServerConfigHistory` e grava configuração e histórico na mesma transação. A alteração passa a valer imediatamente na resolução das permissões dos membros ativos.
- Canais podem ser privados, somente leitura ou ter permissões próprias. O acesso a canais privados é concedido exclusivamente por cargos individuais autorizados, sem concessão individual direta a usuários. `@everyone` nunca concede acesso a canal privado e suas permissões gerais não substituem as regras específicas do canal. A união de permissões entre cargos individuais continua válida; o proprietário mantém acesso especial a todos os canais privados. Somente o proprietário configura quais cargos têm acesso a cada canal privado; `manage_roles` não concede essa autoridade. Concessões e remoções devem ser autorizadas no backend, registradas na auditoria e executadas transacionalmente.
- O proprietário sempre pode visualizar e acessar todos os canais privados do próprio servidor, independentemente dos cargos e permissões funcionais; essa exceção não se estende automaticamente a administradores ou moderadores e exige autenticação e validação do servidor correto.
- `@everyone` pode ser mencionado coletivamente; a menção requer permissão específica como `mention_everyone` e alcança somente membros ativos que podem acessar o canal da mensagem.
- Apenas membros ativos participam das permissões. Saída voluntária e expulsão encerram a participação (`LEFT`), registram `left_at` e removem todas as atribuições individuais de cargos; nenhuma delas cria banimento. Qualquer membro pode sair quando quiser, exceto o proprietário atual, que deve transferir a propriedade antes. Membros que saíram ou foram expulsos podem retornar mediante convite válido e demais regras de entrada. A reentrada reutiliza o registro único em `(server_id, user_id)`, atualiza `joined_at`, limpa `left_at` e não restaura cargos antigos.
- `kick_members`, `ban_members`, `unban_members`, `manage_invites` e `manage_roles` são permissões independentes. Outras permissões administrativas não concedem nenhuma delas implicitamente. Membro comum com `manage_roles` só pode conceder permissões que já possui efetivamente; alterações de JSONB e atribuições de cargos não podem contornar essa regra, autopromover nem elevar alvo acima de sua autoridade. Expulsão exige `kick_members` e hierarquia superior para membros comuns; banimento exige `ban_members` e hierarquia superior e só pode atingir membro `ACTIVE`; revogação exige `unban_members` e hierarquia superior ao snapshot da posição mais alta do usuário no momento do banimento. Membros de mesma hierarquia não agem uns contra os outros. O proprietário pode configurar todas as permissões aprovadas em cargos comuns, expulsar ou banir qualquer membro ativo, revogar qualquer banimento e criar/revogar convites sem essas permissões ou comparação hierárquica. Cargos `is_system_role` permanecem imutáveis também para o proprietário. O proprietário não pode expulsar/banir a si mesmo nem ser expulso/banido por outro membro.
- Banimentos são restrições independentes de `LEFT`, permanecem ativos até revogação manual e impedem entrada mesmo com convite válido. Cada ciclo gera novo registro em `ServerBans`, incluindo `target_highest_role_position` capturado antes da remoção dos cargos. A revogação não reativa a participação automaticamente.
- Convites podem ser criados e revogados pelo proprietário ou por membro com `manage_invites`; qualquer usuário autenticado pode aceitá-los se cumprir as regras de entrada. Tokens seguros são armazenados somente como hash; aceitação valida expiração, revogação e limite de usos, consulta banimento antes de consumir o convite e consome convite e ativa/reutiliza a participação atomicamente. Se o usuário já estiver `ACTIVE`, a API retorna `409 Conflict` sem consumir o convite nem alterar associação, cargos, permissões ou `joined_at`.
- A estrutura de auditoria de moderação é separada dos ciclos de banimento. A decisão de produto prevê eventos de kick, ban, unban, transferência de propriedade e concessão/revogação de acesso a canais privados; no código atual, `ServerAuditLog` é emitido para `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED`. Eventos de banimento/revogação referenciam o ciclo correspondente. Alterações de `everyone_permissions` usam `ServerConfigHistory`. A política aprovada não prevê expiração automática de auditoria; identificadores históricos devem ser preservados e dados pessoais podem ser anonimizados quando necessário.
- O proprietário pode consultar banimentos ativos e revogados e toda a auditoria. Membros com `unban_members` podem consultar somente banimentos ativos. As permissões `kick_members` e `ban_members` não concedem consulta de banimentos; auditoria completa é exclusiva do proprietário.
- Expulsão e banimento registram participação `LEFT`, `left_at` e removem cargos individuais. Expulsão não impede retorno; banimento ativo impede. Operações repetidas sobre participação já `LEFT` retornam erro.
- O proprietário não pode ser removido ou banido por outro membro e não pode sair enquanto continuar proprietário. Pode transferir a propriedade a qualquer membro ativo e não banido do mesmo servidor, sem exigir cargo administrativo. As autoridades especiais passam imediatamente ao novo proprietário e deixam de valer para o antigo. O backend registra `OWNERSHIP_TRANSFERRED` em `ServerAuditLogs` e a alteração de `owner_id` em `ServerConfigHistory` na mesma transação.
- Toda autorização é verificada no backend, nunca apenas na interface.
- `ServerRole.is_default` não representa `@everyone`: este é uma configuração implícita armazenada separadamente em `Server.everyone_permissions`. O código atual não atribui significado funcional a `is_default`; sua finalidade permanece pendente de decisão após análise dos dados existentes.
- A proteção operacional de cargos marcados `ServerRole.is_system_role` está aplicada nos serviços de edição e exclusão, inclusive contra o proprietário. A identificação dos cargos específicos que receberão essa marca continua pendente; não inferir por nome, posição ou `is_default`.
- O serviço `app/services/server_authorization_service.py` implementa `get_member_hierarchy_level(db, server_id, user_id)` e `is_hierarchy_comparison_approved(db, server_id, actor_user_id, target_user_id)`. A comparação valida participação `ACTIVE` de ambos no mesmo servidor; participação ausente ou `LEFT` resulta em 404. O proprietário pode agir hierarquicamente sobre membros ativos independentemente da posição; um membro comum precisa estar estritamente acima do alvo e não pode agir sobre o proprietário. Autoação, níveis iguais e níveis inferiores retornam `False`. A função não concede a permissão específica; o ID do ator deve vir do principal autenticado. O nível não incorpora a autoridade especial do proprietário, separada em `ResolvedServerPermissions.is_owner`. O CRUD e a atribuição/remoção de cargos, além dos serviços de kick/ban/unban, aplicam autorização e hierarquia em seus fluxos.
- A API implementa criação, aceitação, listagem paginada e revogação de convites em `POST /servers/{server_id}/invites`, `POST /servers/{server_id}/invites/accept`, `GET /servers/{server_id}/invites` e `DELETE /servers/{server_id}/invites/{invite_id}`. Proprietário ou membro ativo com `manage_invites` pode criar/listar/revogar. Tokens imprevisíveis são gerados com segurança e apenas seu hash SHA-256 é persistido; o token original é retornado somente na criação. Aceitação valida expiração, revogação e usos, verifica banimento ativo antes do consumo e cria ou reativa a participação atomicamente, sem restaurar cargos.
- A API implementa kick, ban, unban, listagem de banimentos e consulta de auditoria em `POST /servers/{server_id}/members/{user_id}/kick`, `POST /servers/{server_id}/members/{user_id}/ban`, `GET /servers/{server_id}/bans`, `POST /servers/{server_id}/bans/{ban_id}/unban` e `GET /servers/{server_id}/audit-logs`. As ações usam as permissões independentes `kick_members`, `ban_members` e `unban_members`, a hierarquia aprovada e a exceção do proprietário. A auditoria persistida registra `MEMBER_KICKED`, `MEMBER_BANNED` e `MEMBER_UNBANNED`; o unban não reativa participação nem restaura cargos.
- A última execução completa reportada foi `464 passed, 0 failed, 0 skipped`, utilizando exclusivamente o PostgreSQL de testes `plataforma_tcc_test` em `127.0.0.1:55432`. Esse resultado é histórico e não foi executado novamente nesta atualização documental.
- Validações mais recentes informadas separadamente: 32 testes backend nos módulos de análise e API oficial; 32 testes frontend em 7 arquivos; `npm run build` aprovado. Também foi reportada uma validação real da integração OpenAI em duas denúncias de exemplo, preservadas como evidências. Esses resultados não representam a suíte completa do backend e não foram reexecutados nem conferidos no banco durante esta atualização documental.
- A especificação técnica detalhada e os pontos ainda pendentes estão em [ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md](ESPECIFICACAO_AUTORIZACAO_SERVIDORES.md).

### Convites

- Armazenar somente hash de tokens seguros. Proprietário ou membro com `manage_invites` pode criar e revogar convites, que podem ter expiração e limite de usos. A aceitação é autenticada e transacional; banimento ativo é verificado antes do consumo.
- Essas regras têm implementação HTTP nas quatro rotas acima. A listagem é paginada e não expõe token original nem hash; a aceitação exige usuário autenticado, consome o uso na mesma transação da entrada e reutiliza participação `LEFT` sem recuperar cargos antigos.

### Moderação e proteção

- Moderadores oficiais da plataforma são distintos dos moderadores de servidores.
- IA auxilia análise e triagem de denúncias; não aplica banimentos definitivos por conta própria.
- Denúncias relevantes são encaminhadas a moderadores humanos oficiais. Registrar falsos positivos.
- Rejeitar uma denúncia não deve punir automaticamente quem denunciou.
- Penalidades progressivas: primeira infração confirmada, advertência; segunda, suspensão temporária; terceira, banimento permanente. Infrações graves podem exigir medidas excepcionais após análise humana.
- Mensagens privadas não são analisadas automaticamente. Análise de mensagens em servidores depende de habilitação pelo proprietário.
- Essa regra de moderação de mensagens em servidores é uma decisão de produto, ainda sem fluxo implementado, porque mensagens de canais de servidor não existem na API atual.
- Denúncias manuais continuam disponíveis com a IA desabilitada.
- Registrar no histórico as alterações da configuração de moderação por IA.
- “Protegido por IA” indica apenas que a análise está habilitada; não é garantia de segurança. A pontuação de segurança de 0 a 100 é separada dessa classificação.

No código atual, denúncias de mensagens privadas são criadas somente por ação explícita de participante autorizado da conversa. A denúncia e a evidência baseada na mensagem original são persistidas juntas; isso não dispara análise automática no envio de mensagens. A triagem por equipe oficial ativa é a barreira antes de qualquer chamada externa: pode autorizar análise ou manter o caso em revisão humana. A triagem pode registrar suspeita de conteúdo de exploração sexual infantil, exige justificativa e torna a tarefa inelegível para envio à OpenAI. Nenhum conteúdo é enviado nesses casos; não existe classificador automático alternativo para essa finalidade. A análise elegível usa a OpenAI Moderation API com `omni-moderation-latest`, encaminhando somente o snapshot da mensagem denunciada. O resultado é sinal para revisão, não punição; a decisão final é humana e auditável. A fila persistente usa estados, tentativas limitadas, lease e token de reivindicação para recuperação e concorrência. O worker fica desabilitado por padrão e só pode iniciar com `MODERATION_WORKER_ENABLED=true` e `OPENAI_API_KEY` configurada.

### Estado atual da implementação de servidores

Além das rotas descritas nas decisões de produto, o código possui serviços e endpoints de kick, ban, unban, consulta paginada de banimentos e auditoria de moderação. `ServerBan` e `ServerAuditLog` são estruturas reais; a auditoria de servidores cobre kick, ban e unban. Convites também estão implementados, incluindo reentrada e bloqueio por banimento ativo. Denúncias de mensagens privadas, triagem oficial, análise elegível pela OpenAI e decisão humana também estão implementadas. Permanecem pendentes transferência de propriedade, canais privados e mensagens de servidores; a presença de moderação de denúncias não implica esses fluxos.

### Denúncias de mensagens privadas e análise

- `POST /reports` cria uma denúncia de mensagem existente por participante ativo da conversa, rejeita autodenúncia e duplicidade do mesmo denunciante para a mensagem, e persiste a denúncia e o snapshot de evidência na mesma transação. O snapshot preserva conteúdo original, autor e timestamps existentes; a exclusão visível da mensagem não altera a evidência. O cliente não fornece o conteúdo da mensagem.
- A equipe oficial é distinta dos moderadores de servidor. Rotas `/official/reports` exigem `PlatformStaff` ativo e não revogado. A fila permite listar denúncias, consultar detalhe/evidência, consultar análise, registrar triagem humana e gravar decisão humana auditável.
- Uma denúncia começa pendente de triagem. A recusa de análise externa ou suspeita de conteúdo sensível mantém o caso disponível para revisão humana. Suspeita de exploração sexual infantil, registrada com justificativa na triagem, impede envio externo; não se afirma que a OpenAI identifique esse conteúdo com segurança.
- A integração OpenAI é executada por worker persistente após aprovação humana, com o modelo `omni-moderation-latest`. A análise registra modelo, classificação, categorias e scores, sem sanções automáticas. Falhas, tentativas, lease e recuperação são controlados pela fila persistente. A configuração padrão não inicia o worker.

### Canais de voz

- Áudio em tempo real, mute, controle de volume e lista de participantes.
- Salas temporárias podem ser removidas quando vazias.
- Capacidade padrão de 25 participantes, configurável.
- Permissões para visualizar, conectar, falar e gerenciar participantes.
- Registrar entrada e saída, sem gravar o áudio.
- Compartilhamento de tela está previsto com WebRTC.

### Outras funcionalidades planejadas

- Notificações personalizáveis por servidor e canal.
- Menções a usuários, `@everyone` e `@here`, respeitando permissões.
- Retenção de mensagens de servidores configurável: 7, 30, 90 ou 180 dias, ou permanente; padrão permanente.
- Preservar evidências de denúncias em análise. Mensagens privadas permanecem até exclusão pelo usuário.
- Busca textual limitada ao conteúdo acessível ao usuário.
- Verificação de links e avisos de segurança.
- Mensagem de boas-vindas configurável por servidor.
- Arquivos ficam fora do PostgreSQL; o banco mantém metadados e referências.

## Diretrizes para interpretar o projeto

- Requisitos e decisões acima descrevem o produto desejado, não evidência de implementação.
- Um modelo, uma tabela ou uma migration não significa que exista uma funcionalidade utilizável na API.
- Antes de desenvolver, conferir código relacionado, migrations, autorização, constraints, transações, concorrência e testes.
- Quando documentação e código divergirem, registrar a divergência e usar o código real para descrever o comportamento atual.
