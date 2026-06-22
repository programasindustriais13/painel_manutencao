# 🧠 SPEC — CORREÇÃO DE FINALIZAÇÃO DE SERVIÇOS PAUSADOS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/management/` e `/allocations/<id>/finish/`
- **Contexto(s):** Controle de Técnicos (Painel de Gerenciamento)
- **Perfil(s) afetados:** Técnico, Técnico Líder, Operador

---

## ❗ 2. PROBLEMA ATUAL

- **O que está acontecendo hoje?** Ao tentar finalizar um serviço que está com o status "Pausado" (ex: CHECK-LIST do técnico Danilo), o formulário não é processado. O log do servidor registra um `POST /management/ HTTP/1.1" 200`, indicando que a submissão falhou na validação silenciosamente ou o formulário HTML (modal) de serviços pausados está apontando para a URL (action) incorreta em vez de apontar para a rota de conclusão daquela alocação específica.
- **Causa Raiz:** O formulário `#finishAllocForm` dentro do modal `#finishAllocModal` está inicialmente com o atributo `action=""`. O JavaScript é responsável por atualizar dinamicamente a `action` com o ID da alocação correspondente quando o botão "Finalizar" é clicado. Porém, isso é frágil e falha em redirecionamentos de validação malsucedidos no backend, resultando em submissões silenciosas de volta para `/management/` (gerando `POST /management/ HTTP/1.1" 200`). Além disso, as verificações de grupo no template (como `request.user.groups.all.0.name`) são frágeis e impedem superusuários ou usuários com múltiplos grupos de acessar os botões de ação corretos.
- **Impacto em produção:** Os técnicos não conseguem encerrar serviços que foram pausados, travando o fluxo de trabalho.

---

## 🎯 3. OBJETIVO

- O botão "Finalizar" da lista de serviços pausados deve abrir o modal correspondente, submeter os dados (com a observação obrigatória) para a URL correta (`/allocations/<id>/finish/`) e processar o encerramento com sucesso (HTTP 302), exibindo a mensagem na tela.
- O modal de finalização de alocações pausadas deve ser individualizado no template HTML para cada alocação pausada dentro do loop (`id="finishAllocModal-{{ p_alloc.id }}"`), eliminando a necessidade de JavaScript frágil para definir o atributo `action` dinamicamente.
- Substituir verificações de grupos frágeis (como `request.user.groups.all.0.name`) por variáveis de contexto robustas (`user_can_manage` ou `tech.id == technician_proprio_id`).

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [maintenance/templates/maintenance/technician_management.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/technician_management.html) (Foco principal: corrigir o `<form action="...">`, IDs dos modais dos serviços pausados e validações de grupo no HTML).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- Não alterar a lógica de finalização de serviços que estão em atendimento (ativos).
- Não criar novos apps ou refatorar o painel TV.
- Não alterar estrutura de banco de dados.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ❌ Não criar múltiplos ambientes (.venv2, etc)
- ❌ Não duplicar projeto ou apps
- ❌ Não duplicar lógica existente
- ✅ Reutilizar código existente
- ✅ Validar permissões no backend
- ✅ Usar ORM do Django
- ❌ Não usar SQL direto

---

## ⚙️ 7. REGRAS DE NEGÓCIO

- O modal de finalização de um serviço pausado deve exigir o preenchimento obrigatório do campo `observacao_conclusao`.
- Ao concluir um serviço pausado, o sistema deve registrar a `data_fim`, fechar o tempo do serviço e mudar o status da alocação para concluído, além de deixar o técnico 'OCIOSO' (se não houver outros serviços).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Funcionalidade funciona conforme esperado (Serviço pausado finaliza com sucesso).
- [ ] Não quebrou funcionalidades existentes (Serviços em atendimento continuam finalizando normal).
- [ ] Interface compreensível (Feedback de erro caso a observação esteja em branco).
- [ ] Sem duplicação de modais invisíveis quebrando o HTML.
- [ ] Compatível com SQLite e MySQL.
- [ ] Sem duplicação de dados.

---

## ⚠️ 9. RISCOS

- Múltiplos modais gerados no HTML com os mesmos IDs de campo. Devemos individualizar os IDs dos campos (`id_fa_observacao_conclusao-{{ p_alloc.id }}`) para garantir que não haja conflitos de ID no DOM e a validação do navegador funcione.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Inspecionar `technician_management.html` no bloco que renderiza o dropdown/lista de serviços pausados.
2. Mudar a definição do modal de finalização de alocação pausada para dentro do loop de alocações pausadas (`{% for p_alloc in paused %}`), utilizando IDs únicos (`finishAllocModal-{{ p_alloc.id }}`).
3. Ajustar o botão "Finalizar" correspondente para abrir o modal correto (`data-bs-target="#finishAllocModal-{{ p_alloc.id }}"`).
4. Verificar a tag `<form>` dentro desse modal para garantir que a `action` está apontando para a URL correta (`{% url 'finish_allocation' p_alloc.id %}`).
5. Atualizar os campos dentro do modal para usar IDs únicos (`id_fa_observacao_conclusao-{{ p_alloc.id }}` e `id_fa_foto_anexo-{{ p_alloc.id }}`).
6. Ajustar a lógica Javascript de auto-reabertura do modal pós-falha de validação backend para usar o novo ID do modal (`#finishAllocModal-XYZ`).
7. Remover lógica do setup do modal dinâmico no Javascript, pois agora o modal é renderizado com dados e actions estáticos.
8. Substituir as verificações de grupo frágeis (`request.user.groups.all.0.name == ...`) por `user_can_manage` e `tech.id == technician_proprio_id`.
9. Executar os testes unitários (`python manage.py test`) para garantir que nenhuma regressão foi introduzida.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/management/`.
2. Pausar um serviço ativo de um técnico.
3. Abrir a lista de pausados do técnico e clicar em "Finalizar".
4. Preencher a observação no modal e submeter.
5. Confirmar se a requisição redirecionou com HTTP 302 e se o serviço foi encerrado.
6. Testar com observação em branco e garantir que o modal reabre com mensagem de erro.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
