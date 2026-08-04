# 🧠 SPEC 06F — INTEGRAÇÃO UX, TELA DE DETALHE DA CAVIDADE, DESEMPENHO E DEPLOY

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<int:machine_id>/cavidades/<int:cavity_id>/`, `/producao/maquinas/<id>/`
- **Contexto(s):** Módulo de Produção — Consolidação das SPECs 06A a 06E, implementação da Rota e Tela de Detalhes da Cavidade Parada, otimização extrema de consultas ORM (Zero N+1), hardening de produção e deploy.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_06E_PARAMETROS_E_ANOMALIAS_PROCESSO.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Com a conclusão das SPECs 06A a 06E, é necessário consolidar todos os componentes na interface do usuário com navegação fluida, responsiva e industrial.
- Falta implementar a Rota e Tela Específica de Detalhes da Cavidade Parada (`/producao/maquinas/<machine_id>/cavidades/<cavity_id>/`) contendo os 13 pontos exigidos na demanda:
  1. Máquina; 2. Cavidade; 3. Status atual; 4. Início da parada; 5. Tempo total parado; 6. Motivo; 7. Produto; 8. Matriz; 9. Lote/bladder; 10. Técnico(s) responsável(is) vindo(s) da Manutenção (`EM_ATENDIMENTO` ou `EM_PAUSA`); 11. Atualizações parciais do reparo (`AllocationProgressUpdate`); 12. Estimativa de perda de produção; 13. Anomalias de parâmetros relacionadas e histórico recente da cavidade.
- As consultas ao banco local `default` precisam de otimização defensiva (`select_related` e `prefetch_related`) para garantir tempo de resposta HTTP < 200ms no servidor web local/produção sem gargalos N+1.
- O manual de implantação `DEPLOY_WINDOWS_SERVER.md` precisa ser atualizado com as orientações finais de execução do serviço do coletor (`collect_production_scada --interval 60`), scripts de preflight e plano de rollback.

---

## 🎯 3. OBJETIVO

1. **Rota e View de Detalhes da Cavidade:** Criar a rota `/producao/maquinas/<int:machine_id>/cavidades/<int:cavity_id>/` e a view `cavity_detail` apresentando de forma estruturada todos os 13 atributos exigidos.
2. **Navegação no Dashboard:** Ao clicar em uma cavidade parada nos cards de `/producao/`, redirecionar o usuário diretamente para a nova tela de detalhes da cavidade.
3. **Otimização ORM / Performance:** Auditar e aplicar `select_related` e `prefetch_related` em todas as consultas das views `production_dashboard`, `machine_detail` and `cavity_detail`, garantindo 0 queries N+1 e tempo de resposta HTTP < 200ms.
4. **Hardening de Deploy:** Atualizar `DEPLOY_WINDOWS_SERVER.md` e validar execução do coletor background com intervalo 60s em produção.
5. **Suíte Global de Testes:** Garantir aprovação de 100% da suíte de testes (módulos `maintenance` e `production`).

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `production/urls.py`: Adicionar rota `maquinas/<int:machine_id>/cavidades/<int:cavity_id>/`.
- `production/views.py`: Adicionar view `cavity_detail`.
- `production/services.py`: Adicionar método `get_cavity_detail`.
- `production/templates/production/cavity_detail.html` [NOVO]: Layout responsivo de detalhe da cavidade.
- `production/templates/production/dashboard.html`: Ajustar links das cavidades paradas para apontar para a nova rota.
- `production/templates/production/machine_detail.html`: Ajustar links e integrar métricas das SPECs 06A-06E.
- `DEPLOY_WINDOWS_SERVER.md`: Atualizar manual de implantação final.
- `production/tests.py`: Adicionar suíte `Spec06FIntegrationAndPerformanceTestCase`.
- `Instrucoes.txt`: Registrar execução da SPEC 06F.

### Arquivos Proibidos:
- NENHUMA migration nova deve ser gerada nesta SPEC (0 migrations).
- Não alterar regras de negócio dos modelos já criados.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ PROIBIDO executar consultas históricas pesadas ao Scada MySQL dentro da requisição HTTP da view web.
- ✅ Resposta das páginas web servida exclusivamente a partir do banco local `default`.
- ✅ Acesso restrito via decorador `@lider_producao_required`.

---

## ⚙️ 6. REGRAS DE NEGÓCIO E INTERFACE

1. **Tela de Detalhes da Cavidade (`cavity_detail.html`):**
   - **Cabeçalho:** Máquina, Cavidade, Status Atual (badge), Início da parada, Tempo total parado (cronômetro/formatação), Motivo da parada.
   - **Dados Operacionais:** Produto, Matriz, Lote do Bladder, Meta diária, Meta do turno, Realizado no turno.
   - **Responsáveis da Manutenção:** Lista de técnicos da manutenção com atendimento aberto (`EM_ATENDIMENTO` ou `EM_PAUSA`) na máquina. Se nenhum: `"Responsável ainda não atribuído"`.
   - **Atualizações Parciais do Reparo:** Histórico cronológico imutável de `AllocationProgressUpdate` com autor, data/hora e texto da observação parcial.
   - **Estimativa de Perda de Pneus:** Valor aproximado com indicação do nível de fallback e quantidade de amostras válidas.
   - **Anomalias de Processo Relacionadas:** Tabela com anomalias de parâmetros que ocorreram na mesma máquina/cavidade durante a janela da parada.
   - **Histórico Recente:** Tabela dos últimos eventos de parada da cavidade (`ProductionCavityDowntimeEvent`).

2. **Performance Web:**
   - Todas as requisições HTTP devem ser processadas em menos de 200ms.
   - Consultas ORM em `get_cavity_detail` devem usar `select_related` para `machine_config__machine`, `cavity_config` e `prefetch_related` para `matrix_history`, `downtime_events`, `progress_updates`.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Rota e template `cavity_detail` funcionando com a exibição dos 13 itens da demanda.
- [ ] Clicar em uma cavidade parada no dashboard direciona para a nova rota.
- [ ] Responsáveis da Manutenção e Atualizações Parciais renderizados corretamente.
- [ ] Estimativa de perda e anomalias de parâmetro vinculadas apresentadas sem erros.
- [ ] Zero queries N+1 e resposta HTTP < 200ms.
- [ ] Suíte completa de testes unitários (100+ testes) aprovada com 100% de sucesso.
- [ ] Manual `DEPLOY_WINDOWS_SERVER.md` atualizado.

---

## ⚠️ 8. RISCOS

- **Template N+1 no relacionamento inverso:** Garantir `prefetch_related` explicito no service antes de renderizar o template.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Criar `get_cavity_detail` em `services.py`.
2. Criar view `cavity_detail` em `views.py` e registrar rota em `urls.py`.
3. Criar template `cavity_detail.html` com CSS industrial responsivo.
4. Ajustar links no `dashboard.html` e `machine_detail.html`.
5. Atualizar `DEPLOY_WINDOWS_SERVER.md`.
6. Adicionar testes unitários em `tests.py` e executar QA global.

---

## 🧪 10. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar renderização da view `cavity_detail` (HTTP 200), bloqueio de acesso para manutenção, contagem de queries SQL no teste (`assertNumQueries`), e presença dos 13 componentes no contexto.
- **Manuais:** Simular cavidade parada com técnicos em atendimento e notas parciais, clicar na cavidade no dashboard e navegar pela nova tela de detalhes.

---

## 🛡️ 11. DEPLOY, ESTRATÉGIA DE ROLLBACK E GATE DE SAÍDA

- **Rollback:** Reverter alterações de código via `git checkout` / `git revert` sem impacto em banco (0 migrations nesta SPEC).
- **Gate de Saída:** Suíte de testes globais 100% verde + `manage.py check` sem erros.
- **Regra de Parada:** Interromper se qualquer query SQL N+1 for detectada em loops de renderização.
