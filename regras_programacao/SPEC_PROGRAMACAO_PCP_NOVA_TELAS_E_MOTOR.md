# 🧠 SPEC — NOVA PROGRAMAÇÃO PCP / PRODUÇÃO E MOTOR DE CÁLCULO INDUSTRIAL

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/production/pcp/` (nova tela de Programação PCP), `/production/pcp/api/calcular/` (endpoint de prévia dinâmica AJAX), `/production/targets/` (tela legada de metas mantida em transição).
- **Contexto(s):** Dashboard de Gestão, Planejamento de Produção (PCP), Administração Django.
- **Perfil(s) afetados:** PCP / Líder de Produção, Operador, Engenharia.

---

## ❗ 2. PROBLEMA ATUAL

- O cadastro de metas atual depende de digitação manual de quantidade por matriz e data/turno sem cálculo automatizado de janelas produtivas, cavidades paralelas, bladder compatível, perdas estatísticas de processo ou data/hora final estimada.
- O catálogo de matrizes possuía 43 modelos do SCADA sem as informações de tempo de produção, medidas normalizadas ou bladders compatíveis.
- O XLSX `TEMPO_PRODUCAO_E_COD_BLADDER.xlsx` trouxe 55 modelos com tempos atualizados e 10 códigos de bladders vinculados a medidas/tamanhos de matrizes.

---

## 🎯 3. OBJETIVO

1. Substituir/evoluir a experiência manual por uma tela de **Programação PCP** inteligente.
2. Importar de forma idempotente e segura os dados do XLSX para o banco local `default` sem dependência em runtime do arquivo Excel.
3. Reconciliar os 43 códigos canônicos legados do SCADA (preservando IDs 1-43) com os 55 modelos do XLSX e atribuindo novos códigos (44 a 55) para cadastramento manual no PLC.
4. Modelar separadamente Matriz, Medida, Bladder e Compatibilidade (Bladder × Medida).
5. Criar motor de cálculo determinístico para previsão de data/hora final, divisão de metas por turno (respeitando turnos A/06:00-18:00, B/18:00-06:00 e Ambos), restrição de não quebrar ciclo no fim de turno e estimativa estatística de perdas (0,5% Lixo, 1,0% IA).
6. Preservar o banco `scada` como estritamente somente-leitura e integrar os alvos calculados com o Dashboard existente via compatibilidade `ProductionTarget`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `production/models.py`
- `production/admin.py`
- `production/forms.py`
- `production/views.py`
- `production/urls.py`
- `production/services.py`
- `production/management/commands/import_production_planning_data.py`
- `production/templates/production/pcp_plan_form.html` (e visualização de planos)
- `production/tests.py`

---

## 🚫 5. FORA DE ESCOPO

- Não escrever no MySQL `scada`.
- Não fazer deploy em produção.
- Não alterar PLC ou cadastrar datapoints diretamente no SCADA-LTS.
- Não apagar histórico existente ou migrations antigas.
- Não duplicar `.venv` ou criar app paralelo.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 projeto e 1 `.venv`.
- Respeitar decorators de acesso (`@lider_ou_operador_required`).
- Usar ORM Django (compatível com SQLite e MySQL).
- Roteamento `scada` estritamente somente-leitura.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Tempo de Produção & Intervalo:** Usar `TEMPO DE PRODUÇÃO` do XLSX. O intervalo entre ciclos (padrão 90s) é configurável no Admin e salvo no banco `default`.
2. **Perdas Estatísticas:** Lixo (0,5%), IA (1,0%), total 1,5% calculados sobre a meta total programada. A meta programada NÃO é inflacionada automaticamente.
3. **Modelagem de Bladders:** Vinculados à Medida/Tamanho da matriz, não ao modelo específico. Medidas sem bladder (`3.25-8`, `100/90-14`) exibem aviso "BLADDER NÃO CADASTRADO".
4. **Cavidades Paralelas:** Capacidade paralela $N$ (ex: 4 cavidades). Total de ciclos em lote $M = \lceil Q / N \rceil$.
5. **Turnos e Ciclos:** Janelas Turno A (06:00-18:00), Turno B (18:00-06:00). Se o ciclo $T_{producao}$ não couber na janela autorizada restante, salta para o início da próxima janela autorizada sem quebrar o ciclo no meio.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Carga do XLSX executada via comando idempotente com `--dry-run`.
- [ ] 43 códigos legados SCADA mantidos (1-43) e 12 novos códigos (44-55) atribuídos.
- [ ] `LISTA_MATRIZES_PLC_SCADA.md` gerado na raiz.
- [ ] Tela PCP funcional permitindo seleção de matriz, quantidade, início, turnos, cavidades e calculando meta por turno, perdas, bladder e término.
- [ ] Testes unitários do importador e do motor PCP passando com 100% de sucesso.
- [ ] `manage.py check` sem erros.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. **Modelos:** Adicionar `ProductionMatrixSize`, `ProductionBladder`, `ProductionPCPSetting`, `ProductionPCPPlan`, `ProductionPCPPlanShiftTarget` e evoluir `ProductionMatrixCatalog`.
2. **Migration:** Migration aditiva em `production/migrations/`.
3. **Importador:** Criar comando `import_production_planning_data`.
4. **Engine & Services:** Criar motor PCP em `production/services.py`.
5. **UI & AJAX:** Form, View, Template e endpoint AJAX em `production/`.
6. **Testes:** Escrever testes abrangentes em `production/tests.py`.
