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

### Frontend previsto

React, TypeScript, Vite e Tailwind CSS estão previstos. Não fazem parte do backend atualmente analisado.

### Organização atual do backend

- `app/main.py`: inicialização FastAPI, inclusão das rotas e verificações de saúde.
- `app/settings.py` e `app/database.py`: configuração e acesso ao PostgreSQL.
- `app/auth.py`: dependência de autenticação JWT.
- `app/schemas.py`: schemas Pydantic.
- `app/models/`: modelos SQLAlchemy.
- `app/routers/`: endpoints de usuários, conversas e mensagens.
- `app/services/`: lógica de conversas diretas e mensagens.
- `migrations/`: configuração e revisões Alembic.
- `docs/especificacao-tecnica.md`: especificação anterior, que pode divergir do código; confirme sempre contra o código e o status atual.

## Decisões de negócio estabelecidas

### Usuários, autenticação e privacidade

- Cadastro com nome de usuário único, e-mail e senha armazenada com hash seguro.
- Verificação de conta e autenticação em dois fatores estão previstas.
- O usuário pode bloquear outras pessoas.
- Preferências de privacidade devem controlar mensagens de desconhecidos, solicitações de amizade, convites para grupos e visibilidade do status online.
- Bloquear alguém não apaga o histórico. Enquanto o bloqueio estiver ativo, novas mensagens entre os envolvidos ficam impedidas; o histórico permanece acessível a ambos.
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
- Membros podem ter vários cargos. Novos membros não recebem automaticamente o cargo padrão.
- O proprietário tem autoridade administrativa especial, não pode perder essa autoridade por ação de moderador comum e não depende de cargos para exercê-la.
- Permissões de cargos são combinadas e respeitam hierarquia. Permissões individuais podem sobrescrever as herdadas conforme precedência a definir.
- Permissões devem ser verificadas no backend, nunca apenas na interface.
- Canais podem ser privados, somente leitura ou ter permissões próprias.

### Convites

- Armazenar tokens com hash.
- Convites podem ter expiração, limite de usos e revogação.

### Moderação e proteção

- Moderadores oficiais da plataforma são distintos dos moderadores de servidores.
- IA auxilia análise e triagem de denúncias; não aplica banimentos definitivos por conta própria.
- Denúncias relevantes são encaminhadas a moderadores humanos oficiais. Registrar falsos positivos.
- Rejeitar uma denúncia não deve punir automaticamente quem denunciou.
- Penalidades progressivas: primeira infração confirmada, advertência; segunda, suspensão temporária; terceira, banimento permanente. Infrações graves podem exigir medidas excepcionais após análise humana.
- Mensagens privadas não são analisadas automaticamente. Análise de mensagens em servidores depende de habilitação pelo proprietário.
- Denúncias manuais continuam disponíveis com a IA desabilitada.
- Registrar no histórico as alterações da configuração de moderação por IA.
- “Protegido por IA” indica apenas que a análise está habilitada; não é garantia de segurança. A pontuação de segurança de 0 a 100 é separada dessa classificação.

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
