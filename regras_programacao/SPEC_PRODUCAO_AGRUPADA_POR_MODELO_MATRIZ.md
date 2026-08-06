# 🧠 SPEC — PRODUÇÃO ACUMULADA E AGRUPADA POR MODELO DE MATRIZ

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `regras_programacao/SPEC_UX_PLANO_PCP_DASHBOARD_E_CAVIDADE.md`
- **URL(s) envolvidas**:
  - `/producao/`
  - `/producao/plano-turno/`
- **Contexto(s)**: Agregação da produção realizada e acumulada por modelo canônico de matriz no turno.
- **Perfil(s) afetados**: PCP, Líder de Produção, Direção.

---

## ❗ 2. PROBLEMA ATUAL

Duas ou mais cavidades em prensas distintas podem fabricar o mesmo modelo de pneu (ex: Prensa 1/Cav 1, Prensa 4/Cav 2, Prensa 7/Cav 1 todas operando o código 3). Se a produção for somada separadamente por cavidade ou por texto, perde-se a visão consolidada do produto no turno.

---

## 🎯 3. OBJETIVO

Agrupar a produção acumulada no turno exclusivamente pelo `codigo_scada` do modelo canônico da matriz. Somar todas as cavidades participantes, comparar com a meta total do modelo e calcular o percentual de cumprimento real.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [production/services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py): `get_shift_production_by_matrix`
- [production/views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/views.py)
- [production/templates/production/dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/dashboard.html)

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não agrupar pela string do nome do produto.
- ❌ Não zerar o acumulado anterior ao ocorrer troca de matriz em uma cavidade.
- ❌ Não consultar `pointvalues` do Scada em tempo de requisição web.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Resiliência total contra resets de contadores do SCADA (troca de matriz ou bladder).
- Consultar agregados/acumulados no banco local `default`.
- Performance: zero N+1.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. O agrupamento é 100% orientado por `codigo_scada`.
2. Troca de matriz em cavidade fecha o `ProductionCycle` anterior no código antigo e inicia o ciclo no código novo, sem apagar a produção acumulada no código antigo.
3. Produtos com `S/C` (Sem Câmara) mantêm agregados isolados dos produtos equivalentes com câmara.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Cavidades com o mesmo `codigo_scada` têm suas produções somadas corretamente.
- [ ] Trocas de matriz mantêm o histórico da produção antiga no turno.
- [ ] Reset do contador do SCADA não afeta a soma acumulada do turno.
- [ ] Suíte de testes automatizados valida o acúmulo por código.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Erro de acúmulo duplo ao reiniciar o serviço do coletor.
- **Mitigação**: Manter controle por `last_scada_counter` e `last_scada_ts` no `ProductionShiftAccumulated`.
