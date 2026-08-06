# 🧠 SPEC — UX DO PLANO PCP NO DASHBOARD E NA TELA DA CAVIDADE

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `regras_programacao/SPEC_PLANO_PRODUCAO_TURNO_PCP.md`
- **URL(s) envolvidas**:
  - `/producao/` (Dashboard de Produção)
  - `/producao/plano-turno/` (Gerenciamento do Plano)
  - `/producao/maquinas/<machine_id>/cavidades/<cavity_id>/` (Detalhe da Cavidade)
- **Contexto(s)**: Interface de usuário para acompanhamento e atalhos contextuais do plano PCP.
- **Perfil(s) afetados**: Líder de Produção, PCP, Operador de Vulcanização.

---

## ❗ 2. PROBLEMA ATUAL

O card de meta em `/producao/` exibe informações genéricas ou ambíguas sobre metas, e a tela da cavidade não possui atalho contextual claro para ajustar a distribuição da meta sem sugerir que a meta pertence individualmente à cavidade.

---

## 🎯 3. OBJETIVO

1. Evoluir o card de meta em `/producao/` para um resumo real do plano do turno com botão "[ Gerenciar plano do turno ]" e tabela resumida de metas.
2. Adicionar na tela da cavidade o card "PLANO DE PRODUÇÃO DO TURNO" com atalho "Ajustar distribuição" que altera o registro canônico único do modelo.
3. Exibir avisos claros quando a cavidade não tiver meta ou a matriz não for identificada.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [production/templates/production/dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/dashboard.html)
- [production/templates/production/cavity_detail.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/cavity_detail.html)
- [production/templates/production/target_list.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/target_list.html)
- [production/templates/production/target_form.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/target_form.html)
- [production/services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py)

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não criar uma segunda meta armazenada dentro da cavidade.
- ❌ Não associar meta silenciosamente quando a matriz não for identificada.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Interface em Português Brasileiro (pt-br).
- Preservar responsividade e estética moderna (cards, badges e tabelas limpas).
- Não depender de JavaScript pesado no cliente.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. O botão "Ajustar distribuição" na cavidade altera o mesmo registro canônico consumido pela tela `/producao/plano-turno/`.
2. Sem matriz identificada: "Não foi possível associar uma meta porque a matriz atual não foi identificada." (não permite envio).
3. Matriz identificada sem meta: "Nenhuma meta associada a este modelo no turno atual." com botão "[ Criar meta no plano do turno ]" pré-preenchido.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `/producao/` exibe card e resumo do plano do turno.
- [ ] Detalhe da cavidade mostra o progresso do modelo e botão contextual.
- [ ] Redirecionamento da cavidade para criação preenche data, turno, matriz, máquina e cavidade.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Usuário confundir limite do bladder com a meta do PCP na cavidade.
- **Mitigação**: Manter os dois cards em seções separadas com rotulagem explícita.
