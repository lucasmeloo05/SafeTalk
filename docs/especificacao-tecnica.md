# Especificação Técnica da Plataforma de Comunicação Segura

**Título provisório:** Desenvolvimento de uma Plataforma de Comunicação Segura com Mecanismos Inteligentes de Moderação e Proteção de Usuários.

## 1. Objetivo do sistema

Desenvolver uma plataforma de comunicação que permita interações individuais e em comunidades, priorizando segurança, privacidade, controle de acesso e mecanismos inteligentes de auxílio à moderação.

A plataforma terá como foco a prevenção de abusos, a proteção dos usuários e a criação de ambientes de comunicação mais seguros.

## 2. Arquitetura tecnológica

Tecnologias definidas para o projeto:

- **Backend:** Python com FastAPI.
- **Banco de dados:** PostgreSQL.
- **ORM:** SQLAlchemy.
- **Migrações:** Alembic.
- **Autenticação:** JWT.
- **Segurança de senhas:** hash com Argon2.
- **Infraestrutura de desenvolvimento:** Docker.
- **Documentação e testes de endpoints:** Swagger/OpenAPI.

## 3. Módulo 1 — Usuários e relacionamentos

Entidades implementadas:

- `users`
- `user_privacy_settings`
- `friendships`
- `blocks`
- `platform_staff`

Funcionalidades previstas:

- Cadastro e autenticação.
- Nome de usuário único e e-mail obrigatório.
- Verificação de conta.
- Configurações individuais de privacidade.
- Solicitações e gerenciamento de amizades.
- Bloqueio de usuários.
- Diferenciação entre administradores e moderadores oficiais da plataforma.

**Situação:** modelos criados e migrations aplicadas ao PostgreSQL.

## 4. Módulo 2 — Servidores e permissões

Entidades implementadas:

- `servers`
- `server_members`
- `server_roles`
- `server_member_roles`
- `server_channels`
- `server_invites`
- `server_config_history`

Regras definidas:

- Um usuário pode possuir vários cargos em um servidor.
- Um membro pode receber vários cargos.
- Novos participantes aguardam atribuição manual de cargo.
- O proprietário possui autoridade administrativa especial, independente dos cargos.
- A hierarquia impede que administradores gerenciem cargos acima de sua própria posição.
- As permissões concedidas pelos cargos são combinadas.
- Servidores não são publicamente descobertos inicialmente.
- Servidores podem ser classificados como +18.
- A moderação por IA é opcional e ativada pelo proprietário.
- Alterações importantes de configuração são registradas no histórico.

**Situação:** modelos criados e migrations aplicadas ao PostgreSQL.

## 5. Módulo 3 — Conversas privadas e grupos

Entidades propostas:

- `conversations`
- `conversation_participants`
- `conversation_invitations`

Regras definidas:

- Conversas individuais e grupos.
- Qualquer usuário pode criar grupos.
- Amigos podem ser adicionados diretamente.
- Não amigos precisam aceitar convites.
- O criador é o administrador inicial.
- Administradores podem gerenciar participantes e promover outros administradores.
- O criador precisa transferir a administração antes de sair.
- Sair de um grupo não apaga o histórico dos demais participantes.
- Bloqueios impedem a comunicação individual entre os envolvidos.

**Situação:** proposta de modelagem. Ainda não implementada.

## 6. Módulo 4 — Mensagens e interações

Entidades propostas:

- `messages`
- `message_edits`
- `message_reactions`
- `message_user_deletions`
- `message_pins`
- `message_attachments`

Funcionalidades previstas:

- Mensagens de texto e voz.
- Envio de arquivos.
- Respostas e threads.
- Reações com emojis.
- Encaminhamento de mensagens.
- Edição durante os primeiros 15 minutos.
- Exclusão para todos durante os primeiros 15 minutos.
- Exclusão individual sem apagar a mensagem dos demais.
- Fixação de mensagens conforme as permissões.

Arquivos serão armazenados fora do PostgreSQL, mantendo no banco apenas seus metadados e referências.

**Situação:** proposta de modelagem. Ainda não implementada.

## 7. Módulo 5 — Notificações e participação em voz

Entidades propostas:

- `notifications`
- `notification_preferences`
- `voice_participation_logs`

Funcionalidades previstas:

- Central de notificações dentro da plataforma.
- Preferências gerais, por servidor e por canal.
- Silenciamento temporário.
- Histórico de entrada e saída de canais de voz.
- Limite inicial de 25 participantes por canal de voz.
- Salas temporárias que podem ser removidas quando ficam vazias.
- Compartilhamento de tela previsto para uma etapa posterior.

A plataforma não gravará o áudio das conversas.

**Situação:** proposta de modelagem. Ainda não implementada.

## 8. Moderação e segurança

Princípios definidos:

- A inteligência artificial auxilia na análise e triagem de denúncias.
- A decisão final sobre punições pertence aos moderadores oficiais da plataforma.
- Evidências de denúncias em análise devem ser preservadas.
- Falsos positivos serão registrados.
- Mensagens privadas não serão analisadas automaticamente.
- A análise de mensagens em servidores depende da ativação pelo proprietário.
- Ações administrativas importantes devem possuir registros de auditoria.
- A plataforma deve limitar tentativas de login, convites, mensagens e denúncias para reduzir abusos.

## 9. Privacidade e retenção

- Mensagens privadas permanecem armazenadas até que o usuário solicite sua exclusão, respeitadas as obrigações de preservação aplicáveis.
- A retenção de mensagens de servidores poderá ser permanente ou de 7, 30, 90 ou 180 dias.
- Evidências de denúncias em análise devem ser preservadas.
- Bloqueios impedem novas interações entre os envolvidos.
- O sistema não armazenará gravações de áudio dos canais de voz.
- Arquivos enviados deverão passar por validação de formato, tamanho e segurança.

## 10. Regras de integridade e autorização

As regras de negócio deverão ser protegidas tanto pela aplicação quanto pelo banco de dados quando apropriado.

Pontos essenciais:

- Impedir relacionamentos duplicados.
- Garantir que cargos e membros pertençam ao mesmo servidor.
- Impedir que mensagens pertençam simultaneamente a uma conversa e a um canal.
- Garantir que respostas e threads pertençam ao mesmo contexto.
- Respeitar bloqueios e configurações de privacidade.
- Validar permissões no backend, sem confiar apenas na interface.
- Preservar históricos importantes para auditoria e moderação.

## 11. Estado atual do desenvolvimento

| Módulo | Situação |
|---|---|
| Usuários e relacionamentos | Implementado e migrado |
| Servidores e permissões | Implementado e migrado |
| Conversas privadas e grupos | Em planejamento |
| Mensagens e interações | Em planejamento |
| Notificações e voz | Em planejamento |

**Observação:** os módulos 3, 4 e 5 ainda precisam de revisão detalhada antes da criação dos modelos SQLAlchemy e das migrations definitivas. Este documento registra as decisões atuais, mas não substitui os testes de integridade e segurança.