# 🧠 SPEC 05C — INTERPRETAÇÃO DOS MOTIVOS DE PARADA DAS CAVIDADES

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/` (Dashboard geral de máquinas), `/producao/maquinas/<id>/` (Detalhe da máquina e histórico de paradas).
- **Contexto(s):** Dashboard de Gestão de Produção e Telemetria em tempo real conectada ao Scada-LTS.
- **Perfil(s) afetados:** Liderança de Produção, Administrador / Superusuário.

---

## ❗ 2. PROBLEMA ATUAL

- A SPEC 05B assumia a existência dos campos `xid_status_cavidade` e `valor_cavidade_produzindo` para determinar individualmente se uma cavidade estava "Produzindo" ou "Parada".
- No Scada-LTS real, não existe XID específico de status por cavidade. O estado da cavidade deve ser inferido exclusivamente a partir do valor recebido em `xid_motivo_parada`:
  - `0`: cavidade Normal / Produzindo;
  - `1` a `11`: cavidade Parada (com motivo correspondente);
  - Nulo, indisponível, falha de leitura ou valor inválido: estado Indeterminado ("Status da cavidade indisponível").
- Além disso, os campos redundantes `xid_status_cavidade` e `valor_cavidade_produzindo` poluem o modelo `ProductionCavityConfig`, o Django Admin e as consultas em lote.

---

## 🎯 3. OBJETIVO

- Corrigir a interpretação do estado das cavidades conforme o funcionamento real do Scada-LTS.
- Remover os campos redundantes `xid_status_cavidade` e `valor_cavidade_produzindo` de `ProductionCavityConfig`, Admin, leitura em lote, serviço, templates e testes.
- Implementar o mapeamento reutilizável de motivos por cavidade (0 a 11) e do motivo geral da prensa (0, 6, 9, 10, 11).
- Garantir a exibição correta dos status da prensa e das cavidades, tratando códigos desconhecidos e valores nulos sem quebrar a interface.
- Preservar integralmente o alerta de 5 minutos da prensa (baseado exclusivamente no estado geral da prensa igual a PARADA há 300s ou mais).
- Criar a migração `0006_remove_status_individual_cavidade`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos afetados:
- `production/models.py`: Remoção dos dois campos de `ProductionCavityConfig`.
- `production/admin.py`: Remoção dos dois campos de `ProductionCavityConfigInline`.
- `production/services.py`:
  - Atualização do mapeamento de lote de XIDs (remover `xid_status_cavidade`).
  - Criação dos dicionários e serviços de tradução de motivos para Cavidades (`CAVITY_REASON_MAP`) e Prensa (`PRESS_REASON_MAP`).
  - Atualização de `build_cavities_data` para inferir o estado da cavidade por `xid_motivo_parada`.
  - Tratamento da exibição do motivo geral da prensa (ocultar em estado `PRODUZINDO`, traduzir em `PARADA`).
- `production/templates/production/dashboard.html` e `machine_detail.html`: Atualização do badge e texto de cavidades e prensa.
- `production/migrations/0006_remove_status_individual_cavidade.py`: Nova migração.
- `production/tests.py`: Atualização dos testes existentes e inclusão dos testes obrigatórios da SPEC 05C.

---

## 🚫 5. FORA DE ESCOPO

- Não alterar a migração `0005_dados_operacionais_cavidades.py`.
- Não alterar regras de permissões, roteador do Scada (`ScadaRouter`), ou modelos não gerenciados.
- Não iniciar a SPEC 06.
- Não acessar ou escrever no banco Scada.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Seguir rigorosamente o `constitution.md`.
- Manter 100% de compatibilidade entre SQLite (desenvolvimento/testes) e MySQL (produção).
- Garantir idoneidade e idempotência nas migrações.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

### Prensa:
1. O estado geral da prensa continua sendo determinado exclusivamente por `ProductionMachineConfig.xid_status_prensa` e `ProductionMachineConfig.produzindo_value`.
2. O motivo geral nunca define se a prensa está produzindo ou parada.
3. Uma prensa pode continuar produzindo mesmo com uma ou várias cavidades paradas.
4. Se a prensa estiver `PRODUZINDO`, motivo geral residual não deve ser destacado.
5. Se a prensa estiver `PARADA`:
   - Código `0`, nulo ou vazio: `"Motivo da prensa não informado"`.
   - Códigos `6` (Falta de Material), `9` (Mecânico), `10` (Elétrica), `11` (Outros): mostrar texto correspondente.
   - Código desconhecido (ex: `12`): `"Motivo não mapeado — código X"`.

### Cavidade:
1. O estado é inferido exclusivamente pelo valor numérico recebido em `ProductionCavityConfig.xid_motivo_parada`:
   - `0`: Normal / Produzindo (badge Normal/Produzindo, motivo exibido nulo/vazio).
   - `1` a `11`: Parada (badge Parada, texto do motivo correspondente):
     - 1 = Troca de Matriz
     - 2 = Troca de Blader
     - 3 = Troca de Anel Blader
     - 4 = Troca Anel Center Post
     - 5 = Ajuste Matriz
     - 6 = Falta de Material
     - 7 = Ajuste de Blader
     - 8 = IA / Lixo
     - 9 = Mecânico
     - 10 = Elétrica
     - 11 = Outros
   - Código numérico não mapeado diferente de zero: badge Parada e texto `"Motivo não mapeado — código X"`.
   - Valor nulo, indisponível, falha de leitura ou texto inválido: badge Indeterminado e texto `"Status da cavidade indisponível"`.
2. Falha de comunicação não pode ser interpretada como parada.

### Alerta de 5 Minutos:
1. Depende exclusivamente de: estado geral da prensa == PARADA, comunicação válida, dado não stale, tempo no estado >= 300 segundos.
2. Cavidade parada NUNCA dispara o alerta geral da prensa.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Migration `0006_remove_status_individual_cavidade` criada e aplicada sem erros.
- [ ] Campos `xid_status_cavidade` e `valor_cavidade_produzindo` totalmente removidos.
- [ ] Mapeamentos de motivos por cavidade e prensa funcionando na camada de serviços.
- [ ] Tratamento seguro de códigos não mapeados e valores nulos/falha de comunicação.
- [ ] Alerta de 5 minutos preservado e isolado de cavidades paradas.
- [ ] Todos os testes da suíte (maintenance, production e total) passando sem erros.

---

## ⚠️ 9. RISCOS

- Quebra de testes anteriores que dependiam dos campos removidos (devem ser adaptados).
- Erro de conversão de tipo ao ler valores nulos ou strings do Scada (tratar com try/except e conversão segura).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. Criar esta SPEC 05C.
2. Atualizar `models.py` e `admin.py` para remover os dois campos.
3. Gerar a migração `0006_remove_status_individual_cavidade`.
4. Atualizar `services.py` com o mapeamento e inferência de estado por cavidade e prensa.
5. Atualizar templates `dashboard.html` e `machine_detail.html`.
6. Atualizar e expandir `tests.py` cobrindo todos os cenários obrigatórios.
7. Executar QA completo e atualizar documentação (`Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md`).
8. Criar um único commit com a mensagem especificada.

---

## 🧪 11. TESTES OBRIGATÓRIOS

- Código 0 da cavidade resulta em Normal.
- Códigos 1 a 11 traduzidos corretamente.
- Código desconhecido não quebra a tela ("Motivo não mapeado — código X").
- Valor nulo resulta em estado Indeterminado ("Status da cavidade indisponível").
- Prensa produzindo com uma cavidade parada.
- Duas cavidades com motivos diferentes.
- Motivo geral da prensa 6, 9, 10 e 11.
- Prensa parada com motivo geral 0.
- Prensa produzindo ignora motivo geral residual.
- Cavidade parada não dispara alerta geral.
- Leitura em lote inclui apenas `xid_motivo_parada`.
- Campos removidos não aparecem no Admin.
- Migration 0006 remove somente os dois campos.
- Dashboard e detalhe exibem textos, nunca apenas códigos conhecidos.
- Regressão integral das suítes `maintenance` e `production`.
