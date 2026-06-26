# 🧠 SPEC — TRANSIÇÃO DE GRUPOS WHATSAPP PARA O BANCO DE DADOS (/ADMIN)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/admin/` e `/relatorio-turno/`
- **Contexto(s):** Disparo de Relatório de Passagem de Turno.
- **Perfil(s) afetados:** Administrador (para cadastro) e Técnicos (para uso).

---

## ❗ 2. PROBLEMA ATUAL

- Na Fase 3, os grupos de WhatsApp foram configurados como um dicionário hardcoded (`WHATSAPP_GRUPOS`) dentro de `views.py`.
- O cliente avaliou a usabilidade e definiu que a gestão de manutenção precisa ter autonomia para adicionar, alterar ou remover grupos de destino diretamente pela interface do Django Admin, sem a necessidade de editar o código-fonte.

---

## 🎯 3. OBJETIVO

- Criar um novo modelo de banco de dados (`WhatsAppGroup`) para armazenar os IDs e os Nomes amigáveis dos grupos.
- Registrar este modelo no Django Admin.
- Atualizar a view do relatório de turno para buscar as opções dinamicamente no banco de dados, em vez de usar o dicionário fixo, mantendo a opção "Meu Número (Teste)" sempre disponível.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py) (Criar o novo modelo `WhatsAppGroup`)
- [admin.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/admin.py) (Registrar o novo modelo no Django Admin)
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Alterar a view para fazer a query no banco de dados)
- [relatorio_turno.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/relatorio_turno.html) (Ajustar o select loop)
- [tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/tests.py) (Ajustar testes para criar instâncias de `WhatsAppGroup` para mockar o select)

### Módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar NADA no microserviço Node.js (`server.js`). A lógica de Rate Limit, Circuit Breaker e envio está perfeita e deve permanecer intocada.
- NÃO alterar a lógica de construção do texto do relatório.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Criar a migration corretamente para a nova tabela.
- ✅ Reutilizar a lógica de envio (a view apenas trocará a fonte dos dados do `<select>`).
- ✅ Usar ORM do Django.
- ❌ Não usar SQL direto.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **O Novo Modelo (`WhatsAppGroup`):**
   - Campos: `nome` (CharField, max_length=100, verbose_name="Nome do Grupo"), `jid` (CharField, max_length=100, unique=True, verbose_name="JID do Grupo") e `is_active` (BooleanField, default=True, verbose_name="Ativo").
   - O campo `jid` deve ser único (`unique=True`).
2. **A View (`relatorio_turno`):**
   - Remover o dicionário `WHATSAPP_GRUPOS`.
   - Fazer uma query: `grupos = WhatsAppGroup.objects.filter(is_active=True)`.
   - Passar esses grupos para o template.
   - A opção "Meu Número (Teste)" deve ser injetada manualmente na lista de opções (ou tratada no template) para que o técnico sempre possa mandar para si mesmo.
3. **O Template (`relatorio_turno.html`):**
   - O `<select>` terá o "Meu Número (Teste)" fixo como primeira opção (value="meu_numero").
   - Em seguida, um loop `{% for grupo in grupos_whatsapp %}` renderizará `<option value="{{ grupo.jid }}">{{ grupo.nome }}</option>`.
4. **Lógica de Envio:**
   - Se o POST vier com `value == 'meu_numero'`, usa o `request.user.technician_profile.whatsapp`.
   - Se vier com qualquer outro valor, valida se existe como um grupo ativo no banco de dados e envia para o Node.js.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Acessar o `/admin/` e conseguir criar um grupo novo (Ex: Nome: "Liderança", JID: "123@g.us").
- [ ] Acessar a tela de Relatório e ver o grupo "Liderança" listado no dropdown, junto com a opção "Meu Número".
- [ ] O envio continua funcionando perfeitamente integrando com o Node.js.

---

## ⚠️ 9. RISCOS

- **Value do Select:** Garantir que o atributo `value` da tag HTML `<option>` esteja enviando o `grupo.jid` exato para o backend, para que o Node.js receba a string correta com o `@g.us`.
- **Migrações:** Garantir migrações seguras e sem quebras de compatibilidade.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Criar o modelo `WhatsAppGroup` no arquivo `models.py`.
2. Executar `python manage.py makemigrations` e `python manage.py migrate`.
3. Registrar o novo modelo no `admin.py`.
4. Refatorar a view `relatorio_turno` no `views.py` para consultar o banco e validar os destinos com base nos grupos ativos cadastrados.
5. Ajustar o loop de opções no template `relatorio_turno.html`.
6. Atualizar os testes no `tests.py` para criar objetos `WhatsAppGroup` de teste para o mock de envio de grupo.
7. Executar a suíte de testes do Django para validar.

---

## 🧪 11. TESTES MANUAIS

1. Acessar o Painel de Administração do Django (`/admin/`).
2. Cadastrar um novo grupo de WhatsApp (ex: Nome = "Manutenção Geral", JID = "987654321@g.us").
3. Acessar a tela de relatório de turno `/relatorio-turno/`.
4. Validar se a opção "Meu Número (Teste)" é exibida primeiro.
5. Validar se o grupo "Manutenção Geral" é listado na sequência.
6. Enviar o relatório selecionando o grupo e validar no console do Node.js que o JID correto `987654321@g.us` foi recebido e processado.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

(Será preenchido no final)
