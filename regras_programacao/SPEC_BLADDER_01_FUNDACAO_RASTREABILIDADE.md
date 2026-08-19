# 🧠 SPEC — RASTREABILIDADE DE BLADDERS: PARTE 01 — FUNDAÇÃO, XIDs, MODELO DE HISTÓRICO E COLETOR

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** Coletor em background (`collect_production_scada`), Admin Django (`/admin/production/`), Services de backend de Produção.
- **Contexto(s):** Módulo de Produção, Coleta SCADA-LTS em lote, Rastreabilidade Industrial de Bladders.
- **Perfil(s) afetados:** Líder de Produção, Engenharia de Processos, Operação.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, o sistema monitora o ciclo da cavidade via `ProductionCycle`, porém `ProductionCycle` é encerrado em qualquer reset do contador Scada ou troca de matriz, não refletindo a vida útil contínua e física de um bladder (que pode passar por resets de contador na máquina).
- Não há campos configurados para o XID do BLA real instalado e o XID do motivo da troca do bladder por cavidade.
- Não existe uma entidade dedicada que preserve a identidade rastreável do bladder (`BLA + Lote Completo`) com contagem acumulada de passadas imune a resets.

---

## 🎯 3. OBJETIVO

1. Adicionar os campos opcionais `xid_bla_real` e `xid_motivo_troca_bladder` ao modelo `ProductionCavityConfig` e ao Django Admin.
2. Definir a enumeração padronizada `ProductionBladderChangeReason` com os códigos de 0 a 8.
3. Criar a entidade dedicada `ProductionBladderUsage` (armazenada exclusivamente no banco `default`) para registrar cada segmento de uso físico do bladder em uma cavidade.
4. Implementar funções de normalização canônica para o código BLA (`normalize_bladder_code`) e resolução de BLA esperado por matriz (`get_expected_bladders_for_matrix`).
5. Integrar a leitura dos novos XIDs em lote no coletor `collect_production_scada` / `ProductionStateService.process_scada_cycle()` e no processamento incremental `process_incremental_production()`.
6. Garantir idempotência na contagem de passadas, correlação temporal segura do motivo da troca (buffer pendente com janela) e preservação do histórico contra falhas de comunicação e dados stale.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `production/models.py`
- `production/admin.py`
- `production/routers.py`
- `production/services.py`
- `production/migrations/` (migration aditiva e reversível)
- `production/tests.py`

---

## 🚫 5. FORA DE ESCOPO

- Não escrever nem criar migrations no banco `scada`.
- Não alterar as telas de visualização (escopo da SPEC 02).
- Não bloquear fisicamente prensas nem enviar comandos para PLC.
- Não apagar registros de `ProductionCycle` ou `ProductionShiftAccumulated`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 ambiente virtual e 1 base de código ativa.
- Compatibilidade total entre SQLite e MySQL.
- Roteador `scada` estritamente somente-leitura.
- Migrations aditivas com defaults seguros.
- Queries protegidas contra N+1.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Identidade do Bladder**: Composta por BLA Real (normalizado, ex: `BLA003`) + Prefixo do Lote (`xid_produto`) + Número do Lote (`xid_lote_bladder`).
2. **Abertura de Utilização**: Ocorre na primeira observação estável de uma identidade completa e válida.
3. **Encerramento de Utilização**: Ocorre apenas quando houver alteração estável na identidade (`BLA`, `prefixo` ou `número`). Resets do contador, paradas de prensa ou trocas de turno NÃO encerram a utilização.
4. **Mudança de Cavidade**: Se um mesmo BLA + Lote mudar de cavidade, encerra o segmento anterior e abre um novo segmento na nova cavidade.
5. **Motivo da Troca**: Pertence ao bladder que está saindo. Códigos 1 a 8 são válidos; código 0 significa não informado. Utiliza buffer com janela configurável (15 minutos).
6. **Contagem Idempotente**: Cada delta de produção positivo do SCADA incrementa a utilização ativa no máximo uma vez, imune a reinícios e retries.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `ProductionCavityConfig` possui `xid_bla_real` e `xid_motivo_troca_bladder` configuráveis no Admin.
- [ ] `ProductionBladderUsage` criado com migration aditiva no banco `default`.
- [ ] `normalize_bladder_code` normaliza corretamente `3`, `3.0`, `"003"`, `"bla003"`, `"BLA003"`, tratando zeros e brancos como inválidos/não verificáveis.
- [ ] Leitura dos novos XIDs incluída na consulta em lote do coletor.
- [ ] Utilização é aberta, mantida durante resets do contador e fechada na troca de lote/BLA.
- [ ] Motivo da troca é associado com sucesso à utilização encerrada.
- [ ] Testes unitários cobrindo abertura, incremento, reset, troca e motivo 100% OK.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Atualizar `production/models.py` com novos campos e model `ProductionBladderUsage`.
2. Atualizar `production/routers.py` adicionando `productionbladderusage` aos `LOCAL_MANAGED_MODELS`.
3. Criar e aplicar migration local.
4. Atualizar `production/admin.py` com inline e ModelAdmin para `ProductionBladderUsage`.
5. Implementar helpers de normalização e buffer de motivos em `production/services.py`.
6. Integrar lógica de atualização de `ProductionBladderUsage` no coletor.
7. Escrever testes unitários em `production/tests.py` e validar execução.
