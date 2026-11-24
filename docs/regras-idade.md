# Autodeclaração de idade e servidores +18

O cadastro exige data válida e pelo menos 14 anos completos. O cálculo considera mês e dia com a data UTC do servidor. Nascimentos em 29 de fevereiro completam anos em 1º de março nos anos não bissextos. Datas futuras, anteriores a 1900 e datas inexistentes são rejeitadas.

A data é autodeclarada. Não há envio de documento, biometria ou comprovação de identidade. is_verified continua independente da idade. A data não é retornada em buscas públicas, membros, cargos ou mensagens.

## Contas legadas

POST /users/me/birth-date aceita birth_date e password com sessão JWT válida. O usuário com 2FA precisa de uma sessão completada com segundo fator. A operação bloqueia a linha do usuário, verifica a senha e preenche somente uma data ainda ausente. Repetição ou tentativa de alteração recebe 409. Senha incorreta recebe 403; data inválida ou idade insuficiente recebe 422. Uma data já preenchida é imutável nesta versão. A página Declaração de idade permite esse preenchimento e explica a irreversibilidade.

## Classificação do servidor

POST /servers/ aceita is_adult booleano estrito, com default false. Um usuário menor ou sem data válida não cria servidor +18. PATCH /servers/{id} rejeita is_adult como campo extra, inclusive ao misturá-lo com metadados válidos. A criação e o detalhe retornam is_adult.

Servidores comuns mantêm as regras anteriores. Servidores +18 exigem data válida e pelo menos 18 anos na data do acesso. Proprietário, administradores, moderadores e equipe oficial não possuem exceção etária. A classificação é permanente.

A API filtra a listagem e protege servidor, membros, cargos, permissões, contexto, convites, banimentos, auditoria, canais e mensagens. A operação negada responde 404 com mensagem genérica. Isso inclui leitura, polling, envio, edição, exclusão e denúncia de mensagens de canais. A moderação oficial filtra a fila e protege denúncias de origem +18 para revisores sem idade adequada. O histórico é preservado.

O convite continua necessário. O serviço confere a idade antes de consumir o token, aumentar uses_count ou criar/reativar um membro. O preenchimento de nascimento não reativa participação nem restaura cargos. Participações históricas não elegíveis permanecem preservadas no banco e não permitem acesso.

## Demonstração

1. Cadastrar uma conta com 13 anos e conferir a rejeição. Repetir com 14 completos.
2. Entrar com adulto e criar um servidor marcado +18.
3. Gerar convite e tentar aceitá-lo com menor. Conferir a negação sem consumo.
4. Aceitar o convite com adulto e consultar os canais e mensagens autorizados.
5. Tentar consultar o mesmo servidor por ID com menor ou conta legada sem data.
6. Declarar a data de uma conta legada usando a página Declaração de idade. Repetir a declaração e conferir o conflito.
7. Tentar alterar is_adult por PATCH e conferir a rejeição sem mudanças.

Os campos existentes atendem ao fluxo. Nenhuma migration adicional é necessária. Mudanças nos dados de demonstração devem ocorrer apenas em ambiente autorizado e isolado.

## Limites da validação

O bloqueio por idade é autorização no backend para cada operação HTTP. Classificação do servidor e data já declarada não possuem operação de alteração na API. A política não pretende impedir informação falsa na autodeclaração e não verifica documentos. Correção administrativa de uma data anteriormente preenchida não possui fluxo nesta versão. A demonstração em navegador com contas de teste permanece uma etapa manual.
