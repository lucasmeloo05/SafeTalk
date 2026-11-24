# Demonstração do SafeTalk — integração dos Pacotes A, B e C

Roteiro para 25/11/2026. Os nomes abaixo são perfis fictícios a preparar em ambiente autorizado. Este documento não afirma que essas contas existam no banco de desenvolvimento.

## Preparação do ambiente

Usar PostgreSQL 17 isolado. Para testes automatizados, somente plataforma_tcc_test, usuário tcc_test, host 127.0.0.1 e porta 55432. O Compose de testes define postgres-test e publica 55432:5432. Se o contêiner já existe e está parado, o comando conservador é `docker compose -f docker-compose.test.yml start postgres-test`. Não usar down ou remover volumes. Não executar a suíte enquanto uma demonstração usa o mesmo schema de testes, pois as fixtures criam e desfazem suas próprias tabelas.

O banco de desenvolvimento na porta 5433 não foi inspecionado nem atualizado no Pacote D. Não assumir que sua revisão é o head. Antes de usar qualquer banco persistente, um operador autorizado deve conferir a revisão, obter backup e aprovar a atualização.

Variáveis do backend:
- POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER e POSTGRES_PASSWORD apontando para o ambiente isolado.
- JWT_SECRET_KEY provisionada pelo operador.
- TWO_FACTOR_ENCRYPTION_KEY: chave Fernet própria, diferente da chave JWT. A configuração local foi conferida somente quanto à presença/formato; estava ausente. Provisioná-la sem imprimir seu valor e preservar a chave de instalações já ativas.
- MODERATION_WORKER_ENABLED=false durante ensaios e validações sem serviço externo.
- OPENAI_API_KEY deve estar exportada no ambiente do processo quando houver autorização e necessidade de análise externa real. O worker lê os.environ; uma chave somente no arquivo .env não é suficiente. A inspeção encontrou chave no arquivo, sem exportação no processo de validação.

Não alterar .env de desenvolvimento para ensaiar. Variáveis podem ser provisionadas na sessão exclusiva do processo ou por um gerenciador de segredos. Não copiar saídas com credenciais. No frontend, VITE_API_BASE_URL deve apontar para a API isolada. A origem CORS atualmente permitida é http://localhost:5173; abrir o frontend nesse endereço.

A cadeia disponível contém 20 revisões, com head e21b7c84a603, posterior a b241de8f753a. O Pacote C reutiliza colunas existentes. Em ambiente comprovadamente descartável e autorizado, executar Alembic upgrade head antes de iniciar a aplicação. Nunca executar esse comando com as variáveis do desenvolvimento. Não iniciar o código atual contra um schema anterior às tabelas de 2FA.

Depois de provisionar as variáveis e preparar o schema isolado:
1. Na raiz, executar `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001`.
2. No frontend, configurar VITE_API_BASE_URL na sessão exclusiva e executar `npm run dev -- --host localhost --port 5173 --strictPort`.
3. Conferir /health e a aba Network. Confirmar que as requisições usam a API isolada.
4. Preparar os perfis abaixo por cadastro e convites. A designação PlatformStaff exige preparação administrativa autorizada; ela não é concedida pela interface comum.

## Perfis fictícios

| Perfil | Idade e função | Uso |
| --- | --- | --- |
| Adulto proprietário | Nascimento autodeclarado com mais de 18 anos | Criar servidores e administrar canais |
| Adulto membro | Mais de 18 anos, inicialmente sem cargos | Convite, mensagens e negação no canal privado |
| Administrador de servidor | Adulto, cargo com manage_roles, abaixo do proprietário | Demonstrar hierarquia e somente leitura |
| Adolescente | Exatamente 14 anos completos | Servidor comum e recusa em +18 |
| Conta legada de ensaio | Nascimento ausente, criada somente por preparação autorizada de teste | Negação em +18 e declaração única |
| Staff oficial | Adulto com PlatformStaff ACTIVE | Consultar evidência e registrar triagem humana |

Nunca alterar nascimento ou autoridade de contas reais para produzir um cenário. Para situações históricas artificiais, usar somente fixtures isoladas.

## Ordem de apresentação

### 1. Cadastro e autenticação — cerca de 4 minutos

Tentar cadastrar alguém com 13 anos e mostrar a rejeição. Cadastrar uma conta com 14 completos. Explicar autodeclaração e ausência de verificação documental. Entrar sem 2FA e mostrar uma operação autenticada.

Como adulto, abrir Segurança e 2FA, informar a senha e configurar um autenticador. O QR e a chave são sensíveis: ocultar projeção e gravação nesse momento. Confirmar o TOTP e armazenar as recuperações em local privado, sem exibi-las à banca. Sair e entrar novamente. A senha deve produzir apenas o desafio; o JWT normal surge depois da prova. Aguardar um novo período de 30 segundos após a ativação para não reutilizar o código consumido.

Usar uma recuperação e demonstrar que sua repetição é rejeitada. Um desafio temporário enviado como Bearer a /users/me deve receber 401. No DevTools, não projetar cabeçalhos Authorization nem corpos que contenham códigos ou tokens.

### 2. Servidores e idade — cerca de 4 minutos

Criar um servidor comum e outro +18. Mostrar que a classificação aparece na criação e não pode ser alterada por PATCH. Convidar o adolescente ao servidor comum e demonstrar acesso normal.

Tentar aceitar convite +18 com o adolescente. Esperar 404 genérico, sem consumo do convite ou criação de participação. Tentar o mesmo ID diretamente. Repetir com a conta sem nascimento. Aceitar com adulto e mostrar o acesso permitido.

Na conta legada, usar Declaração de idade com senha. A declaração é privada e aceita somente uma vez. Demonstrar que um cargo administrativo e a propriedade não dispensam idade, usando exclusivamente fixtures quando for necessário representar um estado histórico incompatível.

### 3. Canais e mensagens — cerca de 6 minutos

Preparar canais público e privado pelo backend existente em ambiente de teste. A interface ainda não oferece CRUD completo de canais. Configurar um cargo autorizado ao privado.

Nos detalhes do servidor, abrir canais. Mostrar o canal público com membro ACTIVE. Tentar o privado sem cargo e receber negação por HTTP direto. Atribuir o cargo e conferir acesso.

Enviar uma mensagem. Em uma segunda sessão de navegador, observar a atualização incremental. Editar a própria mensagem em até 15 minutos. Tentar editar mensagem de outro autor e receber 403. Excluir a própria mensagem e observar o placeholder nas duas sessões.

Marcar o canal como somente leitura. O membro e o administrador não podem enviar ou editar. O proprietário pode publicar. A exclusão de mensagem própria continua disponível ao autor com acesso.

Para paginação, preparar mais de 50 mensagens fictícias por ferramenta de teste autorizada. Usar Mensagens anteriores e confirmar ausência de duplicação. Alternar entre canais e servidores com rede lenta no DevTools e conferir isolamento. Não gerar carga artificial em registros reais.

### 4. Denúncia e moderação — cerca de 5 minutos

Denunciar uma mensagem de outro autor. Acessar como staff oficial adulto e conferir texto e origem preservados. Editar/excluir a mensagem e conferir que a evidência original continua intacta.

Retirar acesso ao canal privado e tentar consultar ou denunciar seu conteúdo: esperar 404. Verificar também a recusa de evidência +18 a staff sem idade adequada.

Mostrar PENDING_TRIAGE. Criar denúncia não deve disparar chamada externa. A triagem humana registra justificativa e decide elegibilidade. Suspeita de conteúdo sensível exige revisão humana e não é enviada ao provedor. A IA fornece um sinal e não cria sanções; advertência/suspensão/banimento dependem de decisão humana auditada.

### 5. Regressões — cerca de 3 minutos

Demonstrar conversa privada, amizade e bloqueio. Conferir que bloqueio impede comunicação e leitura conforme a regra existente. Mostrar cargos e hierarquia, convites, auditoria e uma recusa de operação administrativa indevida. Não executar punições ou alterações irreversíveis em contas reais.

## Alternativa sem serviço externo

Manter MODERATION_WORKER_ENABLED=false. Usar denúncia, snapshot e revisão humana. Explicar que o sinal externo depende de triagem, configuração do servidor e disponibilidade do provedor. Resultados com cliente simulado pertencem aos testes automatizados e devem ser apresentados como simulação. Não inventar uma análise externa concluída.

## Evidências e limites

Registrar separadamente execução de pytest, Vitest, build, fluxo HTTP real e validação no navegador. Testes React com serviços simulados não comprovam comunicação navegador–API–PostgreSQL.

A leitura de QR por aplicativo físico, a demonstração simultânea em dois dispositivos e uma análise OpenAI real exigem ensaio manual. Recuperação de senha, apelações, correção administrativa de nascimento, exclusão de conta, mídia/voz, retenção e CRUD completo de canais na interface permanecem fora do conjunto demonstrado.


## Resultados do Pacote D em 24/11/2026

- Backend completo: 724 testes aprovados em 193,51 segundos.
- Frontend completo: 212 testes aprovados em 15 arquivos, em 69,95 segundos.
- Build de produção aprovado.
- Um teste integrado usou HTTP loopback real com Uvicorn, FastAPI e PostgreSQL de testes. Ele combinou cadastro, TOTP, recuperação, JWT, idade, convites, cargos, canais, mensagens e evidência. O provedor externo não foi chamado.
- A cadeia de 20 revisões foi exercitada em schema temporário: upgrade completo, downgrade até base e novo upgrade. Nomes das tabelas e colunas foram comparados aos modelos. O teste usa as funções de migration pelo Alembic Operations, sem consultar ou atualizar a revisão do desenvolvimento.
- Chrome local: login de proprietário fictício, servidores comum e +18, leitura e envio no canal geral, recarga comprovando persistência, troca para avisos sem conteúdo do canal anterior e logout. O frontend utilizou a API temporária na porta 8001 e um schema exclusivo do banco isolado, com sessões SQLAlchemy por requisição e commits reais.
- O navegador embutido não alcançou localhost; o ensaio foi concluído no Chrome do Windows. Foi necessário executar o Vite fora do sandbox. A API e o schema temporário possuem encerramento programado; o Vite do ensaio foi encerrado.
- A renovação de JWT pelo 2FA agora reagenda o timer de sessão do frontend. Um teste com timers falsos reproduziu o encerramento antecipado anterior e validou a correção.

O ensaio no Chrome não cobriu leitura do QR em aparelho físico, login 2FA pela UI, duas sessões observando simultaneamente o polling, paginação com grande volume ou rede artificialmente lenta. Esses pontos permanecem no roteiro manual. Os testes de componentes desses cenários usam serviços simulados.
