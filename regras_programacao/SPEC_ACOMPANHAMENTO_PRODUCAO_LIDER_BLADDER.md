# SPEC — Acompanhamento da produção na página inicial do Bladder

Data: 17/11/2026. Implementação autorizada após avaliação da alternativa de nova tela; decisão do usuário: aproveitar `/bladder/`.

## Contexto e problema

A página inicial do líder destacava indicadores de OPs programadas no dia, estoque e saldos, mas não oferecia consulta cronológica dos apontamentos por processo. A ficha de uma OP mostrava tabela longa; o turno limitava os registros recentes; o relatório mensal trabalhava com fechamentos. O líder precisava ver registros atuais e históricos, filtrar por OP ou setor e exportar os mesmos dados consultados.

## Objetivo e escopo

Transformar a página inicial existente em ponto de acompanhamento do líder, com lista resumida, detalhe sob demanda, filtros e exportação Excel. Reusar `ApontamentoTurnoBladder`, `AmostraManuseioBladder`, `HistoricoApontamentoBladder`, autenticação do líder, ficha da OP e `openpyxl`. Não criar nova página de listagem, modelo, migração ou app. Não alterar fechamento, apuração, estoque, DR-201, relatórios mensais ou registros operacionais.

Arquivos principais: `bladder/acompanhamento.py`, `bladder/views.py`, `bladder/urls.py`, `bladder/templates/bladder/dashboard.html`, `bladder/templates/bladder/includes/acompanhamento_producao.html`, `bladder/templates/bladder/base_bladder.html`, `bladder/templates/bladder/ordem_detalhe.html`, `bladder/test_acompanhamento.py` e ensaio Edge existente.

## Decisões de informação e usabilidade

1. Consulta usa `data_turno` do apontamento, independentemente da data programada da OP. O horário exibido é o momento registrado, não telemetria de máquina. O estado `EM_EXECUCAO` da OP não prova atividade instantânea.
2. Resumo inicial conta registros e OPs distintos no filtro, sem somar unidades de processos diferentes. Pendências de manuseio são globais, identificadas como todos os turnos e ligadas ao quadro operacional.
3. A lista mostra somente identificação, momento, processo, produto, operador, quantidade/ausência dela, condição e correção. Parâmetros, amostras e auditoria permanecem no detalhe já existente.
4. Filtros principais: período, OP e processo. Filtros secundários: turma, produto, operador, condição, fechamento aberto/fechado, somente corrigidos e inclusão de legados. Atalhos de período preservam os demais filtros. Paginação de20 itens mantém filtros.
5. Novo histórico exclui `LEGADO` por padrão porque registros antigos podem representar início ou consolidação. Inclusão é explícita e rotulada; filtro de processo considera somente o código registrado, sem inferir processo de legado pela OP.
6. Link da ficha abre a mesma página com OP exata e período derivado dos registros dessa OP, inclusive para ano anterior. Consulta geral limita intervalo a366 dias; OP exata permite período maior.
7. Indicadores e tabela antigos ficam em seção recolhida, acessível. O antigo rótulo “Realizado Hoje” foi corrigido para indicar OPs programadas hoje.

## Exportação e segurança

Endpoint líder em `/bladder/acompanhar/exportar-excel/`, com as mesmas regras de filtro da tela e todos os registros filtrados, inclusive páginas não exibidas. Abas: Consulta, Registros, Amostras e Correções. IDs ligam amostras e correções ao registro e OP. Manuseio não recebe quantidade adicional; não apurado fica vazio e identificado. Valores textuais com prefixos de fórmula são neutralizados antes de escrever a planilha. A rota usa `@lider_bladder_required`; formulário valida enumerações, datas, produto e limite de período. Consultas usam ORM e banco `default`.

## Critérios de aceitação

- A página inicial mostra registros do dia pelo dia do apontamento, mesmo se a OP foi programada antes.
- OP abre histórico próprio e filtros permanecem ao paginar, trocar período e exportar.
- Lista é curta, legível em 375/768px, sem exigir abrir parâmetros para consulta rápida.
- Exportação corresponde ao filtro completo, inclui amostras e correções, preserva identificadores textuais e evita fórmulas.
- Manuseio não aumenta produção; anéis continuam não apurados; legados são distinguíveis.
- Operador/externo não obtêm exportação; data inválida bloqueia exportação.
- `manage.py check`, testes focados e ensaio visual Edge aprovados.

## Validação concluída

- `.venv/Scripts/python.exe manage.py test bladder.test_acompanhamento bladder.test_apontamentos_producao --noinput`:54/54 aprovados (6 novos +48 da entrega anterior), banco temporário Django,3,415s. Testa data do registro, OP histórica, legado, condição/fechamento, paginação20 versus Excel completo, amostras, correções, fórmula maliciosa, datas inválidas e autorização.
- `.venv/Scripts/python.exe manage.py test bladder.tests.BladderEtapa5DashboardTestCase --noinput`:3/4 aprovados. Única falha `test_dashboard_indicadores_principais_e_simplificacao` continua sendo a asserção preexistente `Pendências (Ledger)`, também presente na baseline documentada na SPEC anterior. O rótulo `Realizado Hoje` passou na asserção e foi qualificado para OPs programadas.
- `.venv/Scripts/python.exe scripts/validar_apontamentos_bladder.py`:1/1 aprovado,31,040s, Edge em375/768px. Capturas `logs/apontamentos_bladder/acompanhamento-375.png` e `acompanhamento-768.png` inspecionadas; nenhum overflow horizontal ou erro JavaScript. O ensaio completo também validou criação dos processos, amostras e fechamento em banco temporário.
- `manage.py check`:0 problemas. `makemigrations --check --dry-run`: nenhuma mudança. `git diff --check`:0 erros de espaço.

Consulta somente leitura `manage.py showmigrations bladder` em17/11 mostrou `0011` aplicada no banco `default` deste workspace. Nenhuma migração foi executada nesta tarefa, e o estado do servidor de produção não foi verificado. Esta melhoria não adiciona migração. Não houve deploy, commit, push ou escrita no banco operacional.
