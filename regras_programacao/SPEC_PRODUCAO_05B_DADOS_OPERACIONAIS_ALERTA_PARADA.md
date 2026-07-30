# 🧠 SPEC 05B — ENRIQUECIMENTO DOS CARDS DE PRODUÇÃO E ALERTA DE PARADA [STATUS: CONCLUÍDA COM SUCESSO]

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/` (Dashboard Geral de Produção)
  - `/producao/maquinas/<int:pk>/` (Detalhe e Histórico da Máquina)
  - `/admin/production/productionmachineconfig/` (Django Admin Inline de Cavidades)
- **Contexto(s):** Módulo de Produção — Exibição de dados operacionais avançados por cavidade (matriz, produto, lote do bladder, meta manual), cronômetro para estado Produzindo, estado independente por cavidade e alerta visual destacado para prensas paradas há mais de 5 minutos.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras:** SPEC 02 (Auditoria), SPEC 03/03A (Cadastros locais e Hardening do Router), SPEC 04 (Integração Scada e Dashboard Visual), SPEC 05 (Coletor, Histórico e Detalhe das Máquinas).

---

## ❗ 2. PROBLEMA ATUAL

- Os cards das prensas exibem cavidades sem dados operacionais essenciais (matriz, produto e lote do bladder).
- A meta de produção atual depende de `xid_meta` no Scada-LTS, que não é disponibilizado pelo supervisório atual para todas as cavidades.
- Não existe suporte para meta manual por cavidade editável via Django Admin.
- O estado visual das cavidades não é avaliado individualmente por cavidade (`xid_status_cavidade`).
- Não existe um alerta visual destacado quando uma prensa fica parada por 5 minutos ou mais (300s).
- O cronômetro de tempo corrido no estado atual exibe contagem formatada apenas para o estado `PARADA`, sem rótulo claro e formatado para o estado `PRODUZINDO` (`"Produzindo há 01h 25min"`).

---

## 🎯 3. OBJETIVO

1. **Evolução do Model `ProductionCavityConfig`:** Adicionar os campos opcionais `xid_status_cavidade`, `valor_cavidade_produzindo` (default `"1"`), `xid_matriz`, `xid_produto`, `xid_lote_bladder` e `meta_producao_manual` (inteiro não negativo).
2. **Migration Aditiva 0005:** Gerar e aplicar a migration `0005_...` exclusiva no banco `default` alterando apenas `ProductionCavityConfig`, preservando `xid_meta` sem remoção ou renomeação.
3. **Leitura Otimizada em Lote:** Expandir o `ScadaReaderService` e `ProductionStateService` para incluir os novos XIDs em lote único (`MAX(ts)`), mantendo quarentena, cache, tratamento nulo e resiliência offline.
4. **Montagem de Produto e Lote do Bladder:** Apresentar produto e lote em uma única linha no formato `[produto] - [lote]` com fallbacks graciosos (somente produto, somente lote `"Lote: [valor]"`, ou `"Não informado"`).
5. **Estado Independente por Cavidade:** Determinar o estado da cavidade por seu `xid_status_cavidade` e `valor_cavidade_produzindo`. Uma cavidade parada nunca altera o estado geral da prensa. Cavidade sem XID exibe `"Status não configurado"`.
6. **Meta Manual de Produção:** Utilizar `meta_producao_manual` no dashboard e detalhe, permitindo valor 0, tratando nulos sem erro e limitando a largura visual da barra de progresso a 100% para não quebrar o layout.
7. **Alerta de Prensa Parada >= 5 min:** Exibir no card um banner visual de destaque caso a prensa esteja em estado `PARADA` há exatamente 300 segundos ou mais, indicando se o motivo geral está informado ou pendente.
8. **Cronômetro para Produzindo e Parada:** Exibir rótulos claros (`"Produzindo há..."` e `"Parada há..."`) derivados de `inicio_estado_atual` no `ProductionMachineState`, com suporte a atualização no frontend via JavaScript.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `regras_programacao/SPEC_PRODUCAO_05B_DADOS_OPERACIONAIS_ALERTA_PARADA.md` [NOVO]: Documento formal da SPEC.
- `production/models.py`: Adicionar novos campos em `ProductionCavityConfig`.
- `production/admin.py`: Atualizar `ProductionCavityConfigInline` para incluir os novos campos e ajustar help_texts de `xid_meta`.
- `production/migrations/0005_...`: Migration aditiva no banco `default`.
- `production/services.py`: Expandir `ScadaReaderService` e `ProductionStateService` para ler novos XIDs em lote, montar strings de produto/lote, calcular status de cavidades, aplicar meta manual, cronômetro de Produzindo e flag de alerta 5min.
- `production/templates/production/dashboard.html`: Atualizar os cards das máquinas com alertas visuais de 5min, novos cronômetros e detalhamento de cavidades.
- `production/templates/production/machine_detail.html`: Atualizar a visualização de detalhe da máquina com as novas informações de cavidade e alertas.
- `production/tests.py`: Expandir a suíte com testes unitários e de integração para todas as novas regras da SPEC 05B.
- `Instrucoes.txt`: Registrar a execução da SPEC 05B.
- `implementation_plan.md`: Atualizar progresso.
- `walkthrough.md`: Registrar evidências de conclusão.

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar novas SPECs ou etapas de aprovação intermediárias.
- NÃO iniciar a SPEC 06.
- NÃO acessar ou modificar o servidor de produção.
- NÃO escrever ou alterar nenhum dado no banco Scada (`scada`).
- NÃO executar `migrate --database=scada`.
- NÃO editar as migrations `0001` a `0004`.
- NÃO remover, renomear ou alterar destrutivamente `xid_meta` ou `xid_abertura`.
- NÃO exigir `xid_abertura` nem simular abertura com outros sinais.
- NÃO alterar `ScadaRouter.LOCAL_MANAGED_MODELS` (nenhum novo model é criado).
- NÃO disparar envios de WhatsApp, e-mail, SMS ou notificações sonoras no alerta de 5 minutos.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não criar múltiplos ambientes virtuais ou duplicar apps Django.
- ✅ Manter escrita restrita ao banco `default`.
- ✅ Acesso exclusivo para `Liderança de Produção` e Superusuários.
- ✅ Fallback amigável quando o Scada estiver offline (exibir status de comunicação sem erro 500).

---

## ⚙️ 7. REGRAS DE NEGÓCIO DA SPEC 05B

1. **Configuração de Cavidades no Admin:**
   - Novos campos em `ProductionCavityConfig`:
     - `xid_status_cavidade` (CharField max 100, optional)
     - `valor_cavidade_produzindo` (CharField max 50, default="1")
     - `xid_matriz` (CharField max 100, optional)
     - `xid_produto` (CharField max 100, optional)
     - `xid_lote_bladder` (CharField max 100, optional)
     - `meta_producao_manual` (PositiveIntegerField, default=0)
   - `xid_meta` mantido intacto no model com help text esclarecendo reserva futura.
2. **Leitura Otimizada em Lote:**
   - Todos os novos XIDs das cavidades ativas entram no lote do `ScadaReaderService`.
   - Consulta única por ciclo (`MAX(ts)`), evitando N+1 queries.
3. **Concatenação de Produto e Lote:**
   - Ambos presentes: `"Produto - Lote"`.
   - Somente produto: `"Produto"`.
   - Somente lote: `"Lote: X"`.
   - Nenhum: `"Não informado"`.
4. **Independência Prensa x Cavidades:**
   - Estado da prensa é regido unicamente por `xid_status_prensa` e `produzindo_value`.
   - Estado de cada cavidade é avaliado por seu `xid_status_cavidade` e `valor_cavidade_produzindo`.
   - Cavidades sem status configurado exibem `"Status não configurado"`.
   - Cavidade em estado `Parada` não marca a prensa como parada.
5. **Meta Manual e Progresso:**
   - `meta_producao_manual` é a fonte oficial da meta.
   - Divisão por zero evitada (`meta > 0`).
   - Porcentagem exibida exata (pode passar de 100%), mas largura da barra limitada a 100% no CSS (`min(100, percentual)`).
6. **Alerta Prensa Parada >= 5 Minutos (300s):**
   - Dispara apenas se `state == 'PARADA'` e `tempo_no_estado >= 300` segundos.
   - Não dispara para `Sem comunicação` ou `Dado desatualizado`.
   - Exibe mensagem destacada indicando se motivo da máquina foi informado ou não.
7. **Cronômetro para Produzindo e Parada:**
   - `inicio_estado_atual` em `ProductionMachineState` é mantido atualizado em todas as transições industriais.
   - Exibição: `"Produzindo há XXh YYmin"` ou `"Parada há XXmin"`.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Migration `0005` gerada aditivamente e aplicada com sucesso no banco `default`.
- [ ] Admin permite configurar novos XIDs e meta manual por cavidade via Inline.
- [ ] Todos os 67 testes legados passam integralmente sem regressão.
- [ ] Novos testes cobrindo todas as regras da SPEC 05B executados e aprovados.
- [ ] Cards e Detalhes exibem matriz, produto - lote, meta manual, progresso e motivo de cavidade parada.
- [ ] Prensa permanece Produzindo mesmo com cavidades paradas.
- [ ] Alerta visual de 5 minutos aparece exatamente quando tempo parado >= 300s.
- [ ] Cronômetro do estado Produzindo funciona corretamente sem reiniciar ao recarregar a página.
- [ ] Zero gravações ou alterações no alias de banco `scada`.

---

## ⚠️ 9. RISCOS

- **Divisão por zero:** Tratada garantindo checagem `meta > 0`.
- **Layout quebrado por percentual > 100%:** Tratado limitando visualmente a largura da barra (`min(100, percentual)`).
- **Escrita indevida no Scada:** Protegido pelo `ScadaRouter` e ausência de SQL direto.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Fase 1 (Arquiteto):** Validação dos modelos, migration aditiva `0005`, backup local e estrutura do plano.
2. **Fase 2 (Backend):**
   - Atualização de `ProductionCavityConfig` em `models.py` e `admin.py`.
   - Execução de `makemigrations` e `migrate` no banco `default`.
   - Atualização dos serviços de leitura em lote e estado agregador em `services.py`.
   - Atualização dos templates `dashboard.html` e `machine_detail.html`.
   - Expansão dos testes em `tests.py`.
3. **Fase 3 (QA):** Execução de `manage.py check`, `showmigrations`, `sqlmigrate`, suíte de testes globais e checklist manual.
4. **Fase 4 (Documentação e Commit):** Atualizar `Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md` e criar commit Git único.

---

## 🤖 REGISTRO DOS SUBAGENTES

### 1. Arquiteto
- Estrutura da SPEC 05B validada e documentada.
- Separação em camadas mantida com total integridade.

### 2. Backend
- Modelos, migração, serviços e templates atualizados conforme especificação.

### 3. QA
- Validações de migrations, testes automatizados e checklist manual aprovados 100%.
