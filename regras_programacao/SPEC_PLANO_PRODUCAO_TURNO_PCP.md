# 🧠 SPEC — PLANO DE PRODUÇÃO DO TURNO PCP

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `regras_programacao/SPEC_CATALOGO_CANONICO_MATRIZES_SCADA.md`
- **URL(s) envolvidas**:
  - `/producao/plano-turno/`
  - `/admin/production/productiontarget/`
- **Contexto(s)**: Gestão de Metas e Planejamento de Produção PCP por Turno.
- **Perfil(s) afetados**: PCP, Líder de Produção, Superusuário.

---

## ❗ 2. PROBLEMA ATUAL

A meta de produção cadastrada manualmente era associada diretamente ou de forma difusa a cavidades no `ProductionCavityConfig`, gerando ambiguidades com o limite de ciclo do bladder vindo do SCADA.

---

## 🎯 3. OBJETIVO

Modelar o Plano de Produção do Turno em um model `ProductionTarget` no banco `default`, onde a fonte canônica da meta é a combinação de **Data + Turno + Modelo Canônico da Matriz**, permitindo planejar metas mesmo para matrizes ainda não instaladas.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [production/models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py): `ProductionTarget`
- [production/forms.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/forms.py): `ProductionTargetForm`
- [production/views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/views.py): Views de criação/edição/cancelamento
- [production/urls.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/urls.py): Rota `/producao/plano-turno/`

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não gravar meta do PCP no banco Scada.
- ❌ Não associar obrigatoriamente uma meta a uma cavidade física para existir no plano.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Validação rigorosa no backend (CSRF, POST-Redirect-GET, mensagens Django).
- Permissão restrita a Superusuário, Líder de Produção e usuários autorizados do PCP.
- Bloqueio no backend contra requisições diretas sem permissão.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. Fonte canônica: `Data + Turno + Modelo Canônico de Matriz`.
2. Status permitidos: `PLANEJADA`, `AGUARDANDO_INSTALACAO`, `EM_PRODUCAO`, `ATINGIDA`, `CONCLUIDA_PARCIAL`, `CANCELADA`.
3. Alteração após o início do turno exige registro do usuário, horário e motivo da alteração.
4. Impedir duplicidade de meta canônica para o mesmo turno/data/matriz em registros ativos.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Métodos CRUD funcionam perfeitamente na rota `/producao/plano-turno/`.
- [ ] Usuários sem permissão são bloqueados no backend.
- [ ] Alterações pós-início de turno registram auditoria.
- [ ] Testes cobrem criação, edição e tentativa de duplicidade.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Duplicação de metas de produção em trocas de turno.
- **Mitigação**: UniqueConstraint condicional/efetiva sobre `(data, shift, modelo_matriz)` excluindo metas canceladas.
