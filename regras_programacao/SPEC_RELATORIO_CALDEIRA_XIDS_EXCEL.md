# 🧠 SPEC — RELATÓRIO DA CALDEIRA 2, CADASTRO DE XIDS E EXPORTAÇÃO EXCEL

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/relatorios/` (Central de Relatórios de Máquinas — catálogo com novo card "Caldeira 2")
  - `/producao/relatorios/caldeira/` (Relatório Histórico Web da Caldeira 2)
  - `/producao/relatorios/caldeira/exportar-excel/` (Exportação Excel multi-abas pronta para impressão)
  - `/producao/configuracao-scada/caldeira/` (Central de Configuração amigável dos 9 XIDs da Caldeira)
  - `/producao/configuracao-scada/` (Hub de Configuração SCADA com atalho para a Caldeira)
- **Contextos:**
  - Central de Relatórios de Máquinas (`machine_reports_hub`)
  - Gestão e Auditoria de Utilidades Industriais (Vapor, Condensado, Ar Comprimido, Vácuo)
  - Central de Configuração SCADA (`xid_config_dashboard`)
- **Perfis afetados:**
  - Líder de Produção, Operador, PCP, Admin (`@lider_producao_required` para consulta e exportação)
  - Superusuário (`@superuser_required` para edição e teste de XIDs)

---

## ❗ 2. PROBLEMA ATUAL

- A Central de Relatórios de Máquinas (`/producao/relatorios/`) possui apenas o relatório da Calandra.
- A Caldeira 2 e as linhas de distribuição de vapor (Prensas 1-7 e Prensas 8-12), utilidades auxiliares (ar comprimido e vácuo) e totalizador de condensado não possuem um relatório analítico histórico com indicadores, gráficos sincronizados e exportação executiva em Excel.
- Os 9 XIDs de telemetria da Caldeira 2 precisam de uma tela amigável para visualização, edição, teste em tempo real de comunicação com o Scada-LTS e restauração de padrões canônicos, sem depender do Django Admin.
- A linha de vulcanização possui assimetria física (Prensas 1 a 7 = até 14 cavidades; Prensas 8 a 12 = até 18 cavidades), exigindo análise descritiva e comparativa sem limites arbitrários ou conclusões automáticas de falha.
- O totalizador de condensado (`VOLUME_CAL` / `DP_153208`) é acumulativo em litros e precisa de algoritmo robusto para cálculo de volume por diferença de leituras e detecção de resets/rollovers.

---

## 🎯 3. OBJETIVO

- Implementar o **Relatório Histórico da Caldeira 2** no módulo de Produção, perfeitamente integrado à central `/producao/relatorios/`.
- Adicionar tela amigável de configuração dos 9 XIDs da Caldeira em `/producao/configuracao-scada/caldeira/`.
- Criar serviço analítico `CaldeiraHistoricalService` em `production/services_caldeira.py` para sincronização temporal, cálculos de desvio do setpoint, diferenças entre linhas, diferenças Caldeira × linhas e volume de condensado por deltas positivos.
- Gerar exportação Excel (.xlsx) profissional com 3 abas (`Resumo Gerencial`, `Gráficos`, `Dados Históricos`), logo oficial da Freedom, formatação brasileira e layout pronto para impressão A4 em paisagem.
- Garantir 100% de reutilização de infraestrutura (coletor `collect_production_scada`, modelo `ProductionGlobalParameter`, `ScadaReaderService`, permissões `@lider_producao_required` e `@superuser_required`), sem criar novos apps, sem duplicar coletores e com isolamento total do banco SCADA (somente leitura).

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Módulos e Arquivos:
- `production/services_caldeira.py` [NOVO]: Definição canônica das 9 variáveis, resolução de DataPoints, sincronização temporal (forward-fill), cálculo de estatísticas e desvios, cálculo de condensado e geração do workbook Excel multi-abas.
- `production/views.py` [MODIFICADO]: Adicionar views `caldeira_historical_report`, `caldeira_export_excel`, `xid_caldeira_config`; atualizar `machine_reports_hub` e isolar chaves `caldeira_` em `xid_global_config`.
- `production/urls.py` [MODIFICADO]: Rotas `relatorios/caldeira/`, `relatorios/caldeira/exportar-excel/`, `configuracao-scada/caldeira/`.
- `production/templates/production/caldeira_report.html` [NOVO]: Template web com filtros rápidos (Hoje, Ontem, 7d, 30d, Personalizado), cards de resumo, 6 gráficos Chart.js e tabela sincronizada com paginação.
- `production/templates/production/xid_caldeira_config.html` [NOVO]: Template para gestão dos 9 XIDs agrupados por Geração de Vapor, Linhas de Alta, Linhas de Baixa, Condensado e Utilidades Auxiliares com teste AJAX inline.
- `production/templates/production/machine_reports_hub.html` [MODIFICADO]: Inserir card interativo "Caldeira 2".
- `production/templates/production/xid_config_dashboard.html` [MODIFICADO]: Adicionar atalho para Configuração da Caldeira 2.
- `production/test_caldeira_report.py` [NOVO]: Testes unitários e de integração cobrindo permissões, filtros, cálculos estatísticos, condensado com resets, exportação Excel e integridade.
- `Instrucoes.txt` [MODIFICADO]: Registro completo da nova funcionalidade conforme protocolo.

---

## 🚫 5. FORA DE ESCOPO

- Relatório individual por prensa ou por cavidade.
- Correlação de oscilação de pressão com etapa individual do ciclo de vulcanização.
- Classificação automática de oscilação como defeito, falha ou anormalidade (relatório puramente descritivo e comparativo).
- Alteração no PLC, no Scada-LTS, no script do Meta Data Point ou no K-factor (17314).
- Criação de novo app Django ou banco paralelo.
- Qualquer escrita, DDL ou migration direcionada ao banco `scada`.
- Deploy em produção ou git push.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 ambiente virtual (`.venv`) e 1 base de código ativa.
- Reutilizar `ProductionGlobalParameter` com prefixo `chave="caldeira_<key>"` no banco `default`.
- Banco `scada` estritamente somente-leitura através do `ScadaRouter`.
- Decorators de segurança obrigatórios:
  - `@lider_producao_required` em `caldeira_historical_report`, `caldeira_export_excel` e `machine_reports_hub`.
  - `@superuser_required` em `xid_caldeira_config` e `xid_test_api`.
- CSRF Token em todos os formulários POST.
- Tratamento resiliente de ausência de dados, ausência de logo e indisponibilidade do SCADA sem gerar erro 500 ou stacktrace.

---

## ⚙️ 7. REGRAS DE NEGÓCIO E CONTEXTO INDUSTRIAL

### 7.1. Assimetria das Linhas de Vulcanização
- **Prensas 1 a 7:** 7 prensas × 2 cavidades = até 14 cavidades.
- **Prensas 8 a 12:** Prensa 8 (2 cavidades) + Prensas 9 a 12 (4 cavidades cada) = até 18 cavidades.
- As linhas possuem capacidades instaladas diferentes. Oscilações maiores na linha 8-12 são fisicamente esperadas e não devem ser categorizadas como defeito.
- Adicionar nota de rodapé no relatório web e no Excel:
  > *"Oscilações de pressão podem ocorrer quando várias prensas ou cavidades solicitam vapor simultaneamente. Este relatório apresenta o comportamento medido e não classifica automaticamente uma oscilação como falha. As linhas possuem capacidades instaladas diferentes: até 14 cavidades nas prensas 1 a 7 e até 18 cavidades nas prensas 8 a 12."*

### 7.2. Ciclo Canônico de Vulcanização (Contexto da Planta)
1. **Conformação:** Ar comprimido no bladder molda o pneu verde.
2. **Fechamento e Prensagem:** Prensa fecha e atinge ~150 bar.
3. **Circulação de Alta:** Entrada e saída de vapor de alta no bladder (aquecimento).
4. **Vulcanização:** Somente entrada de vapor aberta, mantendo pressão da linha pelo tempo parametrizado.
5. **Descarga:** Válvula de vapor fecha, abre descarga (primeiros ~10s com injeção pneumática).
6. **Vácuo:** Drenagem de condensado residual e despressurização do bladder.
7. **Abertura:** Pressão interna do bladder < 2 bar para liberar abertura; segunda atuação do vácuo por ~20s.
8. **Troca dos Pneus:** Travas acionadas, retirada do pneu pronto e carregamento de novo pneu verde.

### 7.3. As 9 Variáveis Canônicas da Caldeira 2
1. `pressao_alta_prensas_1_7`: `VALVULA_VAPOR - Press1_PRENSAS 1 A 7` (bar, instantânea, Linhas de alta)
2. `pressao_alta_prensas_8_12`: `VALVULA_VAPOR - Press2_PRENSAS 8 A 12` (bar, instantânea, Linhas de alta)
3. `setpoint_pressao_alta`: `VALVULA_VAPOR - setPress` (bar, instantânea, Geração de vapor)
4. `pressao_caldeira`: `CALDEIRA 2 - PRESSCAL` (bar, instantânea, Geração de vapor)
5. `volume_condensado`: `Meta_Calculos_Prensas - VOLUME_CAL - Volume Condensado` (litros, totalizador acumulativo, Condensado)
6. `pressao_baixa_prensas_1_7`: `VALVULA_VAPOR - PressBX1_PRENSAS 1 A 7` (bar, instantânea, Linhas de baixa)
7. `pressao_baixa_prensas_8_12`: `VALVULA_VAPOR - PressBX2_PRENSAS 8 A 12` (bar, instantânea, Linhas de baixa)
8. `pressao_ar_comprimido`: `VALVULA_VAPOR - AR_COMPRIMIDO_VULC` (bar, instantânea, Utilidades auxiliares)
9. `pressao_vacuo`: `UNIDADE DE VÁCUO - PRESS_VACUO` (bar, instantânea, Utilidades auxiliares)

### 7.4. Cálculos Analíticos
- **Variáveis Instantâneas:** contagem de amostras válidas, média, mínimo, máximo, amplitude ($máx - mín$). Valores nulos/inválidos ignorados sem conversão em zero.
- **Acompanhamento de Setpoint (Amostra a Amostra):**
  - $\Delta_{1-7} = Press1 - setPress$
  - $\Delta_{8-12} = Press2 - setPress$
  - Desvio médio assinado, desvio absoluto médio ($MAD$), maior desvio absoluto, mínimo e máximo.
- **Comparação entre Linhas:**
  - Diferença Alta $= Press1 - Press2$
  - Diferença Baixa $= PressBX1 - PressBX2$
- **Diferença Caldeira × Linhas de Alta:**
  - $PRESSCAL - Press1$
  - $PRESSCAL - Press2$
- **Volume de Condensado (`VOLUME_CAL`):**
  - Ordenar leituras por timestamp e eliminar duplicatas de timestamp.
  - Para cada par consecutivo: $\Delta = v_{atual} - v_{anterior}$.
  - Se $\Delta \ge 0$: somar ao volume total do período.
  - Se $\Delta < 0$: registrar reset/quebra de continuidade, não subtrair, iniciar novo segmento.
  - Média $L/h = \text{Volume Total} / \text{Horas Cobertas no Intervalo}$.
  - Buscar ponto imediatamente anterior ao filtro para garantir exatidão do primeiro delta.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Card "Caldeira 2" presente em `/producao/relatorios/`.
- [ ] Card genérico "Relatórios de Máquinas" mantido na página inicial do módulo.
- [ ] Tela web `/producao/relatorios/caldeira/` carrega com filtros, cards de KPI, 6 gráficos Chart.js e tabela paginada.
- [ ] Telas de configuração em `/producao/configuracao-scada/caldeira/` permitem editar e testar os 9 XIDs com superuser e bloqueiam usuários não autorizados.
- [ ] Cálculo de condensado trata deltas positivos, identifica resets e calcula taxa horária em $L/h$.
- [ ] Exportação Excel gera arquivo `.xlsx` com 3 abas (`Resumo Gerencial`, `Gráficos`, `Dados Históricos`), logo da Freedom, layout A4 paisagem ajustado para 1 página de largura e aba inicial ativa.
- [ ] Períodos sem dados exibem mensagem informativa amigável sem erro 500.
- [ ] Compatibilidade total SQLite/MySQL e nenhuma tentativa de escrita no banco `scada`.
- [ ] Relatório da Calandra e demais funcionalidades de produção continuam sem regressão.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

| Risco | Mitigação |
|---|---|
| Períodos longos gerando excesso de dados no navegador | Aplicar downsampling inteligente para no máximo 1500 pontos nos gráficos e paginação (50/página) na tabela. |
| Incompatibilidade ou ausência do logo Freedom no Excel | Utilizar fallback elegante de texto institucional e busca resiliente em `maintenance/static/maintenance/img/logo_pneus_freedom_black.png`. |
| Falhas de conexão com o banco SCADA durante teste de XID | Capturar exceções e retornar JSON com status `SCADA_OFFLINE` e mensagem amigável sem stacktrace. |
| Reset do totalizador de condensado distorcendo o consumo | Algoritmo específico de segmentos positivos com contagem de eventos de reset. |

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Serviço Analítico (`services_caldeira.py`):**
   - Configuração canônica das 9 variáveis com grupos, unidades e identificadores.
   - Resolução de DataPoints via `ProductionGlobalParameter` ou fallback canônico.
   - Algoritmo de sincronização temporal (forward-fill) e cálculo das estatísticas de vapor, setpoint, linhas e condensado.
   - Geração de datasets para Chart.js e exportação Excel openpyxl completa.
2. **Views & URLs:**
   - Adicionar `caldeira_historical_report`, `caldeira_export_excel`, `xid_caldeira_config` em `production/views.py`.
   - Registrar rotas em `production/urls.py`.
   - Atualizar exclusão de chaves `caldeira_` em `xid_global_config` e `diagnostics`.
3. **Templates:**
   - Criar `caldeira_report.html` com layout de KPIs, 6 gráficos e tabela.
   - Criar `xid_caldeira_config.html` com teste assíncrono inline de XIDs.
   - Atualizar `machine_reports_hub.html` e `xid_config_dashboard.html`.
4. **Testes Automatizados:**
   - Criar `production/test_caldeira_report.py` cobrindo todas as regras de negócio, permissões, cálculos de condensado e geração Excel.
   - Executar suíte de testes com `python manage.py test production`.
5. **Documentação:**
   - Atualizar `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/producao/relatorios/` e clicar em "Caldeira 2".
2. Testar filtros "Hoje", "Ontem", "7d", "30d" e "Personalizado".
3. Validar cards de KPI, gráficos sincronizados e nota de assimetria das linhas.
4. Exportar Excel e verificar as 3 abas, logo, layout paisagem A4 e dados sincronizados.
5. Acessar `/producao/configuracao-scada/caldeira/` como superuser, alterar um XID, clicar em "Testar" e salvar.
6. Acessar como técnico/operador comum e validar bloqueio de segurança.
7. Testar período sem dados e validar mensagem amigável.
8. Validar que o relatório da Calandra continua 100% funcional.

---

## 🤖 ORQUESTRAÇÃO DE SUBAGENTES

1. **Subagente Arquiteto:** Mapeamento do escopo, validação de reutilização e redação desta SPEC (concluído).
2. **Subagente Backend:** Implementação dos serviços, views, rotas, templates e testes automatizados.
3. **Subagente QA:** Execução da suíte de testes, validação de compatibilidade, inspeção do arquivo Excel e testes de regressão.

---

# 🧠 PRINCÍPIO FINAL
> *"Alterar o mínimo possível para resolver o problema com segurança."*
- Segurança > velocidade
- Clareza > complexidade
- Consistência > criatividade
