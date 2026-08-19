# 🧠 SPEC — RASTREABILIDADE DE BLADDERS: PARTE 02 — TELAS "EM USO", HISTÓRICO E FICHA CONSOLIDADA

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/bladders/` (Bladders em uso), `/producao/bladders/historico/` (Histórico por período), `/producao/bladders/<int:pk>/` e `/producao/bladders/detalhe/` (Ficha detalhada por BLA e lote).
- **Contexto(s):** Módulo de Produção, Visualização Operacional, Auditoria de Vida Útil.
- **Perfil(s) afetados:** Líder de Produção, PCP, Engenharia de Processos.

---

## ❗ 2. PROBLEMA ATUAL

- O líder de produção não tem uma visão consolidada de quais bladders estão atualmente instalados nas cavidades, quantas passadas foram realizadas em relação ao limite de vida e quais são os motivos mais frequentes de troca.
- Não é possível rastrear o ciclo de vida completo de um bladder específico (identificado por BLA + Lote) quando ele passa por diferentes cavidades ao longo do tempo.

---

## 🎯 3. OBJETIVO

1. Criar a tela **"Bladders em Uso"** (`/producao/bladders/`) exibindo a situação atual de todas as cavidades (BLA, lote completo, prensa, cavidade, matriz, passadas, limite, % de vida, tempo em uso, status de setup e filtros rápidos).
2. Criar a tela **"Histórico de Bladders"** (`/producao/bladders/historico/`) com filtros de período (sobreposição temporal), prensa, cavidade, BLA, lote, motivo de troca, paginação backend e cards com KPIs do período.
3. Criar a tela **"Ficha Detalhada do Bladder"** (`/producao/bladders/detalhe/`) consolidando todos os segmentos de utilização de uma identidade `BLA + Lote`, somando passadas sem duplicidade e listando todas as cavidades e trocas registradas.
4. Adicionar item no menu principal da Produção (`base_production.html`) com rotas protegidas por `@lider_producao_required`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `production/views.py`
- `production/urls.py`
- `production/services.py`
- `production/templates/production/base_production.html`
- `production/templates/production/bladder_list.html` [NOVO]
- `production/templates/production/bladder_history.html` [NOVO]
- `production/templates/production/bladder_detail.html` [NOVO]
- `production/tests.py`

---

## 🚫 5. FORA DE ESCOPO

- Não criar polling disparado pela view no SCADA.
- Não carregar todo o histórico de uma vez no navegador (paginação obrigatória no backend).
- Não alterar outras telas não relacionadas do PCP ou Manutenção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Validação de permissões no backend (`@lider_producao_required`).
- Formatação em Português Brasileiro (pt-br).
- Tratamento seguro de campos nulos e valores ausentes.
- Layout responsivo para desktop e mobile.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Regra de Período Histórico**: Utilização é exibida se `inicio <= fim_filtro AND (fim >= inicio_filtro OR fim IS NULL)`.
2. **Consolidação BLA + Lote**: Soma as passadas acumuladas de todos os segmentos da mesma identidade sem duplicação.
3. **Faixas de Vida Útil**:
   - `< 80%`: Normal (verde/padrão)
   - `80% - 94.99%`: Atenção (amarelo)
   - `>= 95%`: Crítico (vermelho)
4. **KPIs do Período**: Total de bladders usados, total de passadas, trocas realizadas, média de passadas e distribuição por motivos de troca.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Telas `/producao/bladders/`, `/producao/bladders/historico/` e `/producao/bladders/detalhe/` acessíveis e funcionais.
- [ ] Filtros e paginação backend preservam querystring.
- [ ] Usuário sem permissão recebe mensagem amigável e é redirecionado.
- [ ] Testes automatizados das views e regras de agregação passam 100%.
