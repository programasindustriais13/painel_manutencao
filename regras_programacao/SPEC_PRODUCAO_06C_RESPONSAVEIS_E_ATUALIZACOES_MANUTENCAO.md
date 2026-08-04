# 🧠 SPEC 06C — RESPONSÁVEIS E ATUALIZAÇÕES PARCIAIS DA MANUTENÇÃO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`, `/management/`, `/admin/maintenance/allocationprogressupdate/`
- **Contexto(s):** Módulo de Manutenção e Módulo de Produção — Vínculo transparente de técnicos da manutenção com as máquinas da produção e registro imutável de atualizações parciais do reparo.
- **Perfil(s) afetados:** Técnicos, Operadores da Manutenção e Liderança de Produção.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_06B_ESTADO_E_PARADAS_POR_CAVIDADE.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, as telas de produção não exibem de forma integrada quais técnicos da Manutenção estão alocados para atender a uma máquina com problema ou parada.
- O técnico de Manutenção não possui um mecanismo nativo para registrar notas de progresso parciais do atendimento (ex: "Center post reparado. Serviço aguardando compra do anel e material de vedação.") sem concluir o serviço ou sobrescrever as observações iniciais.
- É necessário definir a regra de identificação dos responsáveis atuais v vindo das alocações da Manutenção (`maintenance.Allocation`) para a máquina correspondente (`maintenance.Machine`).
- Não se deve duplicar os cadastros de máquinas, técnicos ou alocações.

---

## 🎯 3. OBJETIVO

1. **Vínculo de Responsáveis:** Obter os responsáveis da manutenção para uma máquina da Produção consultando as alocações da Manutenção relacionadas à mesma instância de `maintenance.Machine`:
   - Técnico com alocação `EM_ATENDIMENTO`;
   - Técnico com alocação `EM_PAUSA` (quando o atendimento continuar em aberto e relacionado à máquina/problema);
   - Se houver múltiplos técnicos: exibir todos;
   - Se não houver alocação: exibir `"Responsável ainda não atribuído"`.
2. **Model `AllocationProgressUpdate`:** Criar no app `maintenance` o modelo para histórico imutável de atualizações parciais do reparo.
3. **Interface de Registro na Manutenção:** Permitir que o técnico cadastre atualizações em `/management/` no seu atendimento ativo ou pausado.
4. **Exibição na Produção:** Exibir os responsáveis e o histórico de atualizações parciais na tela de detalhe da máquina/cavidade da Produção em modo de leitura simples.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `maintenance/models.py`: Criar `AllocationProgressUpdate`.
- `maintenance/admin.py`: Registrar `AllocationProgressUpdate`.
- `maintenance/views.py`: Adicionar view/action para registrar atualização parcial do atendimento.
- `maintenance/urls.py`: Adicionar rota `/management/allocations/<id>/update-progress/`.
- `maintenance/forms.py`: Criar formulário de atualização parcial.
- `maintenance/templates/maintenance/technician_management.html`: Adicionar campo/botão para registrar atualização no card do técnico.
- `maintenance/migrations/0013_allocationprogressupdate.py` [NOVA]: Migration aditiva em `maintenance`.
- `production/services.py`: Adicionar método para buscar responsáveis atuais e atualizações parciais de uma máquina.
- `production/templates/production/machine_detail.html`: Exibir bloco de responsáveis e linha do tempo de atualizações parciais.
- `maintenance/tests.py`: Adicionar testes unitários para `AllocationProgressUpdate`.
- `production/tests.py`: Adicionar testes unitários para leitura dos responsáveis e atualizações na Produção.
- `Instrucoes.txt`: Registrar execução da SPEC 06C.

### Arquivos Proibidos:
- Mudar regras de permissão legadas da Manutenção.
- Alterar tabelas do Scada.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ NÃO duplicar tabelas de técnicos ou máquinas na Produção.
- ✅ Validação estrita no backend: técnico só pode adicionar atualização na sua própria alocação.
- ✅ Histórico 100% imutável (sem edição ou exclusão por técnicos comuns).

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Model `AllocationProgressUpdate` (Tabela `maintenance_allocationprogressupdate`):**
   - `allocation`: ForeignKey(`maintenance.Allocation`, related_name='progress_updates', on_delete=CASCADE).
   - `autor`: ForeignKey(`auth.User`, on_delete=SET_NULL, null=True, blank=True).
   - `descricao`: TextField(verbose_name="Descrição da Atualização").
   - `criado_em`: DateTimeField(auto_now_add=True).

   *Meta:* `ordering = ['criado_em']`.

2. **Validação de Permissão de Cadastro:**
   - Técnico com perfil `TECNICO` só pode criar atualização se `allocation.tecnico.user == request.user`.
   - Operadores/Admins podem cadastrar em qualquer alocação aberta.
   - Texto em branco ou composto apenas por espaços deve ser REJEITADO com erro de validação.

3. **Status da Alocação Imutável:**
   - Adicionar uma atualização parcial NÃO altera automaticamente o status da alocação (`EM_ATENDIMENTO` ou `EM_PAUSA`).

4. **Resolução de Responsáveis na Produção:**
   - Para uma `ProductionMachineConfig`, resgatar `machine_config.machine`.
   - Buscar `Allocation.objects.filter(maquina=machine, data_fim__isnull=True, status__in=['EM_ATENDIMENTO', 'EM_PAUSA'])`.
   - Mapear técnicos únicos associados a essas alocações.
   - Retornar string ou lista com nomes dos técnicos ou `"Responsável ainda não atribuído"`.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Model `AllocationProgressUpdate` gerado em `maintenance` e migration `0013` aplicada no `default`.
- [ ] Técnico consegue registrar nota parcial no card de gerenciamento sem encerrar ou pausar o serviço.
- [ ] Histórico de notas exibido em ordem cronológica imutável.
- [ ] Detalhes da máquina na Produção exibem técnicos responsáveis atuais (`EM_ATENDIMENTO` e `EM_PAUSA`).
- [ ] Se não houver alocação aberta, Produção exibe `"Responsável ainda não atribuído"`.
- [ ] Suíte de testes automatizados (maintenance + production) aprovada 100%.

---

## ⚠️ 9. RISCOS

- **Gargalo N+1 nas Views de Produção:** Utilizar `prefetch_related("allocations__progress_updates", "allocations__tecnico")` para carregar responsáveis e notas em lote.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Criar `AllocationProgressUpdate` em `maintenance/models.py` e admin.
2. Gerar e aplicar migration `0013` no app `maintenance`.
3. Criar view e rota de inclusão de atualização em `maintenance/views.py` e `urls.py`.
4. Atualizar card do técnico em `technician_management.html`.
5. Implementar serviço de resolução de responsáveis e histórico de notas em `production/services.py`.
6. Atualizar `machine_detail.html` na Produção.
7. Escrever e rodar testes unitários.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar criação de progresso por técnico dono, rejeição para técnico não dono, preservação de status da alocação, e resolução de múltiplos responsáveis.
- **Manuais:** Criar 2 alocações (uma ativa, outra pausada) para a mesma prensa na Manutenção, registrar notas parciais e verificar a exibição consolidada na tela de Produção.

---

## 🛡️ 12. ROLLBACK E GATE DE SAÍDA

- **Rollback:** `python manage.py migrate maintenance 0012` reverte a migração `0013`.
- **Gate de Saída:** 100% da suíte global de testes aprovada.
- **Regra de Parada:** Interromper se houver tentativa de criar novo cadastro duplicado de técnicos.
