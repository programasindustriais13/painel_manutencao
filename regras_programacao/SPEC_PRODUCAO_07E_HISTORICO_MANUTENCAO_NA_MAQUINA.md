# 🧠 SPEC_PRODUCAO_07E — HISTÓRICO DE MANUTENÇÕES SOMENTE LEITURA NA TELA DA MÁQUINA

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_07D_PRODUCAO_AGRUPADA_POR_MATRIZ.md`
- **URL(s) envolvidas**:
  - `/producao/maquinas/<id>/` (Detalhe da Máquina no Módulo de Produção)
- **Contexto(s)**: Módulo de Produção / Integração com App Manutenção / Visão Integrada do Equipamento
- **Perfil(s) afetados**: Líder de Produção, PCP, Operadores (Visualização)

---

## ❗ 2. PROBLEMA ATUAL

Quando uma prensa entra em parada técnica ou sofre manutenções preventivas/corretivas, os dados de atendimento são registrados pelos técnicos no app `maintenance` (`Allocation`, `HistoricoPausa`, `AllocationProgressUpdate`).
Atualmente, a Liderança de Produção não possui uma visão centralizada desses históricos dentro da página de detalhes da máquina no módulo de produção (`/producao/maquinas/<id>/`).
Por outro lado, a Liderança de Produção **NÃO DEVE** receber acesso geral às rotas de edição/CRUD ou gerenciamento do app `maintenance` (`/management/`, `/cruds/`), preservando o isolamento de perfis e a segurança do controle de técnicos.

---

## 🎯 3. OBJETIVO

Adicionar uma seção **Somente Leitura** dedicada ao Histórico de Manutenções na rota `/producao/maquinas/<id>/` reutilizando estritamente as estruturas existentes de `maintenance`:
1. **Dados Exibidos por Atendimento (Alocação)**:
   - Data/Hora de Início e Término.
   - Status (`EM_ATENDIMENTO`, `EM_PAUSA`, `CONCLUIDO`).
   - Serviço / Atividade descrita.
   - Técnico ou lista de técnicos envolvidos (`Allocation` / `tecnico`).
   - Observação inicial de abertura.
   - Observação de conclusão.
   - Atualizações parciais de progresso (`AllocationProgressUpdate`).
   - Pausas e motivos registrados (`HistoricoPausa`).
   - Tempo bruto de atendimento.
   - Tempo total pausado.
   - Tempo líquido produtivo de reparo.
   - Anexos e fotos permitidos (renderizados via links/modais seguros com fallback para anexos vazios).
2. **Recursos de Interface**:
   - Filtro por Período de Datas (Data Inicial / Data Final).
   - Filtro por Status (`CONCLUIDO`, `EM_PAUSA`, `EM_ATENDIMENTO`).
   - Paginação limpa (padrão 10 registros por página).
3. **Desempenho e Segurança**:
   - Otimização rigorosa contra consultas N+1 utilizando `select_related('tecnico', 'operador')` e `prefetch_related('pausas', 'progress_updates')`.
   - Acesso estritamente somente leitura dentro do contexto do módulo de produção.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py):
  - Expandir o método `get_machine_detail` para consultar e formatar a lista paginada de manutenções da `maintenance.Machine`.
- [templates/production/machine_detail.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/machine_detail.html):
  - Adicionar a aba/seção "Histórico de Manutenções da Máquina" com tabela responsiva, filtros e modais de detalhes.
- [tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/tests.py):
  - Adicionar testes de integração e contagem de queries (N+1).

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO criar novos modelos de manutenção (reutilizar obrigatoriamente `maintenance.Allocation`, `HistoricoPausa`, `AllocationProgressUpdate`).
- ❌ NÃO conceder aos usuários do módulo de produção acesso a rotas de escrita ou formulários do app `maintenance`.
- ❌ NÃO realizar migrações de banco para esta SPEC.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Não duplicar tabelas de manutenção.
- Fallback seguro para anexos ou fotos inexistentes.
- Otimização N+1 com ORM nativo.

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS

1. **Cálculo dos Tempos de Manutenção**:
   - `Tempo Bruto` = `data_fim` (ou `now` se em aberto) - `data_inicio`.
   - `Tempo Pausado` = Soma das durações de todas as pausas registradas em `HistoricoPausa` para a alocação.
   - `Tempo Líquido` = `max(0, Tempo Bruto - Tempo Pausado)`.
2. **Múltiplos Técnicos**:
   - Se a mesma máquina teve mais de um atendimento simultâneo ou sequencial no mesmo período, agrupar e listar todos os técnicos responsáveis.
3. **Anexos e Midia Protegida**:
   - Links para fotos/anexos devem utilizar o manipulador seguro de mídia com fallback visual caso o arquivo físico tenha sido removido do servidor.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Na rota `/producao/maquinas/<id>/`, o histórico de manutenções exibe as ordens concluídas, pausadas e em atendimento da máquina.
- [ ] Exibe técnico(s), serviço, pausas, motivos, atualizações parciais, observações e cálculo de tempos (bruto, pausado e líquido).
- [ ] Filtros de período e de status funcionam corretamente com paginação de 10 registros por página.
- [ ] Usuários da Liderança de Produção não conseguem editar nem acessar rotas de escrita da Manutenção.
- [ ] Testes de consulta N+1 garantem no máximo 3 a 5 queries SQL para carregar a página inteira de detalhes.
- [ ] Suíte de testes automatizados passa 100%.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Lentidão ou N+1 ao carregar histórico com centenas de atendimentos e pausas.
  - *Mitigação*: Paginação com `django.core.paginator.Paginator` (10 itens/página) + `select_related` e `prefetch_related`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Implementar método auxiliar `get_machine_maintenance_history` em `ProductionStateService` (`production/services.py`).
2. Adicionar filtros por data, status e suporte ao `Paginator`.
3. Renderizar a tabela de histórico em `production/templates/production/machine_detail.html`.
4. Criar testes automatizados simulando atendimentos pausados, múltiplos técnicos e verificação de permissões.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados:
- `test_machine_detail_renders_maintenance_history`: cria alocações concluídas e pausadas e verifica exibição na rota.
- `test_maintenance_history_nplusone_prevention`: utiliza `self.assertNumQueries` para garantir ausência de N+1.
- `test_production_user_cannot_access_maintenance_edit_routes`: verifica se usuário com perfil de Produção é bloqueado em `/management/` ou rotas de post da Manutenção.

---

## 🛑 12. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Testes de histórico de manutenção e N+1 100% aprovados.
- **Regra de Parada**: Se for detectada duplicação de models de manutenção no app `production`, PARAR e importar diretamente de `maintenance.models`.
