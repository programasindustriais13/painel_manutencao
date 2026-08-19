# 🧠 SPEC — RASTREABILIDADE DE BLADDERS: PARTE 03 — VALIDAÇÃO AUTOMÁTICA DE SETUP E QUALIDADE

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** Dashboard `/producao/`, Detalhe da Máquina `/producao/maquinas/<id>/`, Detalhe da Cavidade `/producao/maquinas/<id>/cavidades/<id>/`, Telas de Bladders `/producao/bladders/`.
- **Contexto(s):** Qualidade e Prevenção de Erros de Setup, Validação Automática Matriz × BLA.
- **Perfil(s) afetados:** Líder de Produção, Inspetor de Qualidade, Operador.

---

## ❗ 2. PROBLEMA ATUAL

- Se um operador instalar um bladder com código BLA divergente do especificado para a matriz em produção, o sistema não alerta os líderes nem registra o evento histórico e a quantidade de pneus produzidos durante a incompatibilidade.

---

## 🎯 3. OBJETIVO

1. Implementar máquina de estados centralizada para validação de setup:
   - `CORRETO`: BLA real pertence ao conjunto canônico de bladders da matriz instalada.
   - `EM_TRANSICAO`: Divergência recente aguardando confirmação por janela de leituras consecutivas ($N$ leituras).
   - `INCORRETO`: Incompatibilidade confirmada e persistente.
   - `NAO_VERIFICAVEL`: Dados incompletos, matriz sem cadastro, BLA ausente ou comunicação indisponível.
2. Criar a entidade histórica `ProductionBladderSetupMismatchEvent` no banco `default` para registrar cada ocorrência confirmada com snapshot de prensa, cavidade, matriz, BLA esperado, BLA real, timestamps e passadas produzidas.
3. Contabilizar de forma transacional e idempotente as **passadas produzidas durante o setup incorreto**.
4. Exibir badges explícitos nos cards de cavidade e banners/KPIs persistentes no Dashboard `/producao/` enquanto houver divergência confirmada.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `production/models.py`
- `production/admin.py`
- `production/routers.py`
- `production/services.py`
- `production/templates/production/dashboard.html`
- `production/templates/production/cavity_detail.html`
- `production/templates/production/machine_detail.html`
- `production/tests.py`

---

## 🚫 5. FORA DE ESCOPO

- Não parar automaticamente máquinas ou enviar comandos PLC.
- Não gerar falso alerta na primeira leitura transitória (estabilização obrigatória).
- Não criar tabela concorrente para o relacionamento Matriz × BLA.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas detecção, alerta e registro (sem intertravamento físico de máquina).
- Alertas visuais claros com texto e cor (acessibilidade).
- Gravação exclusiva no banco `default`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Estabilização contra Falsos Alertas**: Uma divergência precisa persistir por $N$ leituras consecutivas (padrão 3 leituras) para abrir um evento confirmado de `INCORRETO`.
2. **Contagem de Passadas no Erro**: Passadas ocorridas durante `EM_TRANSICAO` são incorporadas ao evento apenas se a divergência for confirmada.
3. **Encerramento do Evento**: Ocorre quando o BLA for corrigido de forma confirmada, ou na troca de matriz/bladder.
4. **Dado Desatualizado / Stale**: Congela o estado de validação sem abrir ou fechar eventos.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `ProductionBladderSetupMismatchEvent` registrado e persistido corretamente.
- [ ] Divergência rápida em transição não gera evento histórico se normalizar.
- [ ] Divergência persistente gera exatamente 1 evento aberto e acumula passadas produzidas.
- [ ] Dashboard exibe banner e KPI persistente com tempo e passadas em erro.
- [ ] Testes automatizados de validação de setup e contagem de passadas 100% OK.
