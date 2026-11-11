# Instruções para agentes neste repositório

1. Antes de implementar uma funcionalidade, leia os arquivos relacionados e entenda a arquitetura existente.
2. Nunca presuma que algo está implementado apenas porque existe um modelo ou uma tabela.
3. Não modifique funcionalidades existentes sem necessidade.
4. Preserve as decisões de negócio documentadas em `CONTEXTO_TCC.md`.
5. Priorize segurança, autorização no backend e integridade dos dados.
6. Considere transações, concorrência, constraints e integridade referencial.
7. Antes de criar uma migração, analise as migrações anteriores e os modelos registrados.
8. Nunca execute migrações destrutivas sem autorização explícita.
9. Crie testes para as funcionalidades implementadas e execute-os.
10. Não declare uma funcionalidade concluída sem verificar seu funcionamento.
11. Ao encontrar divergências entre código e documentação, informe antes de fazer alterações.
12. Não invente evidências, resultados de testes ou funcionalidades.
13. Não exponha senhas, tokens, chaves secretas ou dados pessoais.
14. Não altere `.env` nem envie credenciais ao Git.
15. Prefira mudanças pequenas, completas e coerentes.
16. Ao concluir uma tarefa, informe arquivos criados/modificados, regras implementadas, testes executados e resultados.
17. Não faça commits ou pushes sem solicitação explícita.
18. Se uma decisão de negócio estiver ambígua, pergunte antes de implementar.

## Referências do projeto

- `CONTEXTO_TCC.md` registra objetivo, arquitetura pretendida e decisões de negócio. Requisitos não significam implementação existente.
- `STATUS_PROJETO.md` registra o estado observado do código, endpoints, modelos, migrações, pendências e problemas conhecidos. Confirme o código atual antes de usar esse status como evidência após novas mudanças.
- `docs/especificacao-tecnica.md` é documentação anterior e pode estar desatualizada; confronte-a com o código e com `STATUS_PROJETO.md`.
