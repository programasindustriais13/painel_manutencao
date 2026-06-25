# 🧠 SPEC — GERADOR DE RELATÓRIO DE PASSAGEM DE TURNO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** 
  - `/technicians/<id>/edit/` (Cadastro / Edição de Técnico)
  - `/relatorio-turno/` (Nova Rota para Passagem de Turno)
- **Contexto(s):** Controle de Técnicos e Fechamento de Turno
- **Perfil(s) afetados:** Técnico, Técnico Líder e Operador

---

## ❗ 2. PROBLEMA ATUAL

- A passagem de turno hoje é feita de forma manual. Os técnicos (incluindo líderes que atuam na operação) gastam tempo digitando no WhatsApp tudo o que foi executado durante o dia, com alto risco de esquecer de relatar pendências críticas (como máquinas que ficaram pausadas).
- Não há um campo no banco de dados para salvar o número do WhatsApp do técnico, impedindo futuras integrações de disparo de mensagens.

---

## 🎯 3. OBJETIVO

- **Cadastros:** Adicionar o campo `whatsapp` no modelo do Técnico (`Technician`).
- **Tela de Relatório:** Criar uma nova tela onde o Técnico ou Técnico Líder acessa no final do turno. O sistema compilará automaticamente um texto de prévia listando as alocações concluídas no dia atual e mapeando as pendências. Esse texto será exibido em uma área editável (`<textarea>`).
- **Ação Simular:** O botão de enviar apenas exibirá uma mensagem de sucesso na tela usando Django Messages, preparando o terreno para a integração real com a API Node.js na próxima fase.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py) (Adicionar campo `whatsapp` no Technician).
- [forms.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/forms.py) (Adicionar `whatsapp` no formulário `TechnicianForm`).
- [urls.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/urls.py) (Nova rota `/relatorio-turno/`).
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Lógica de montagem da string do texto e renderização da view).
- [technician_form.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/technician_form.html) (Adicionar campo no formulário).
- [base.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/base.html) (Adicionar o botão de "Passagem de Turno" no menu).
- [NEW] `maintenance/templates/maintenance/relatorio_turno.html` (Nova tela com o textarea e layout da fábrica).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO implementar a integração real com o Baileys/WhatsApp nesta etapa (isso será a Fase 2).
- NÃO alterar a lógica de conclusão de serviços.
- NÃO apagar os campos existentes do técnico.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Criar migration segura para o novo campo de telefone.
- ✅ Reutilizar o código existente e a base visual do Bootstrap já em uso.
- ✅ Validar permissões no backend (Somente Técnico, Técnico Líder e Operador podem acessar a tela).

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Adição de Campo:** No modelo `Technician`, adicionar `whatsapp = models.CharField(max_length=20, null=True, blank=True)`.
2. **Busca de Dados:** A view `/relatorio-turno/` deve buscar apenas as instâncias de `Allocation` vinculadas ao técnico atualmente logado (`request.user.technician_profile`) cuja data de início ou fim ocorra na data atual (hoje).
3. **Lógica de Construção do Texto (String):**
   - **Cabeçalho:** `Boa noite\nPassagem de turno\n`
   - **Corpo (Concluídos):** Para cada serviço com status `CONCLUIDO` do dia, adicionar uma linha: `* [observacao_conclusao]` (Se não houver observação de conclusão, colocar a `atividade_observacao` de abertura ou o nome da máquina).
   - **Rodapé (Pendências):** O sistema deve checar se o técnico possui alguma alocação do dia com status `EM_ATENDIMENTO` ou `EM_PAUSA`.
     - Se NÃO houver: Adicionar `Sem pendências para o próximo turno`.
     - Se HOUVER: Adicionar `Pendências para o próximo turno:\n* [Nome da Máquina] - [Status/Motivo da Pausa]`.
4. **Interface Editável:** Injetar esse texto montado diretamente dentro de uma tag `<textarea>` no HTML, permitindo que o técnico leia, apague erros de digitação e complemente o texto antes de "Enviar".
5. **Botão de Envio:** O formulário deve fazer um POST (salvando as edições temporárias ou apenas disparando uma mensagem via Django Messages de "Relatório gerado com sucesso - Em breve integrado ao WhatsApp!").

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Consigo salvar um número de WhatsApp no cadastro do técnico.
- [ ] O Técnico, Técnico Líder e o Operador com perfil de técnico vinculado conseguem acessar a tela de Relatório.
- [ ] A tela exibe o texto pré-compilado exatamente no formato solicitado, mapeando corretamente as concluídas e as pendentes do dia atual.
- [ ] O texto é editável pelo usuário na interface.
- [ ] O envio do formulário gera uma mensagem de sucesso no Django Messages.

---

## ⚠️ 9. RISCOS

- **Filtro de Data (Timezone):** Garantir que a view utilize a data local atual (fuso horário configurado no Django, preferencialmente usando `timezone.now().date()` ou `timezone.localdate()`) para evitar que turnos noturnos da madrugada quebrem o relatório.
- **Migration:** O campo `whatsapp` deve aceitar valores nulos (`null=True, blank=True`) para não quebrar a base dos 26 técnicos já cadastrados.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Modificar o `models.py` (adicionar `whatsapp` em `Technician`) e rodar `makemigrations` + `migrate`.
2. Adicionar o campo no `TechnicianForm` em `forms.py`.
3. Adicionar o campo no template `technician_form.html`.
4. Criar a nova view `relatorio_turno` em `views.py`.
5. Escrever a lógica de query (filtrando por `data__date=hoje` ou intervalo e pelo técnico logado) e concatenar a string do texto.
6. Criar o template `relatorio_turno.html` exibindo a `textarea` e o botão simulação.
7. Adicionar atalho visual no menu/navbar em `base.html` para acessar essa tela.

---

## 🧪 11. TESTES MANUAIS

1. Acessar como Operador, editar um técnico e adicionar o número (ex: 3199999999).
2. Fazer login como este Técnico.
3. Iniciar um serviço qualquer hoje e concluir preenchendo uma observação.
4. Iniciar outro serviço e deixar em Pausa.
5. Clicar no botão "Passagem de Turno".
6. Validar se a caixa de texto mostra a concluída com o asterisco `*` e alerta sobre a máquina pausada no final.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
