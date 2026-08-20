# PROMPT — FASE 7: TESTES INTEGRADOS DE QA, AUDITORIA DA CONSTITUIÇÃO & DOCUMENTAÇÃO

## 📌 Contexto & Objetivo
Após a implementação de todas as fases, esta etapa final valida a consistência de ponta a ponta do sistema, assegura conformidade total com as regras da `constitution.md` e consolida a documentação técnica no arquivo `Instrucoes.txt`.

---

## 🔒 Auditoria de Conformidade com a `constitution.md`

Verificar e garantir os seguintes pontos obrigatórios:
- [ ] **Ambiente Único:** Apenas 1 ambiente virtual (`.venv`), 1 projeto Django e nenhuma duplicidade de pastas ou código.
- [ ] **Compatibilidade de Banco de Dados:** Todas as queries e models são compatíveis tanto com **SQLite** (desenvolvimento) quanto com **MySQL** (produção).
- [ ] **Segurança Backend:** Nenhuma ação ou rota crítica depende apenas do frontend; todos os decorators (`@operador_required`, `@lider_ou_operador_required`, `@tecnico_or_operador_required`) estão ativos e testados.
- [ ] **Regra de Concorrência:** Impossibilidade estrita de um mesmo técnico ter 2 alocações com status `'EM_ATENDIMENTO'` simultaneamente.
- [ ] **Modo TV (`/tv/`):** Atualização automática preservada em 10 segundos, sem barras de rolagem e com destaque de técnicos ociosos.
- [ ] **Fallback Seguro:** O sistema não quebra sob nenhuma hipótese caso fotos não sejam enviadas ou APIs externas falhem.

---

## 🧪 Roteiro de Testes Integrados (QA de Ponta a Ponta)

### 1. Testes de Roteamento e Portal
- [ ] Login com usuário `tecnico1` (somente técnico) -> Redirecionamento direto para `/management/`.
- [ ] Login com usuário `lider_prod` (somente produção) -> Redirecionamento direto para `/producao/`.
- [ ] Login com usuário `admin` (acesso duplo) -> Redirecionamento para `/portal/` com os dois cards operacionais.
- [ ] Dentro do Módulo Produção, clicar no logo "PAINEL PRODUÇÃO" -> Permanece em `/producao/` sem ser expulso para a manutenção.
- [ ] Testar alternância rápida no menu superior ("Trocar de Módulo").

### 2. Testes de Cadastro de OS e Leitura por Foto / IA
- [ ] Abertura de OS por upload/foto -> Scanner IA preenche os campos automaticamente.
- [ ] Teste de duplicidade: tentar cadastrar o mesmo número de OS duas vezes -> Sistema bloqueia e emite alerta claro.
- [ ] Teste de resiliência: simular ausência de chave de API -> Sistema permite preenchimento manual imediato sem erros 500.

### 3. Testes do Fluxo Operacional e Múltiplos Técnicos
- [ ] OS criada com status `PENDENTE` aparece na aba de Pendentes do Quadro de OSs.
- [ ] Operador atribui técnico -> OS exibe o técnico designado.
- [ ] Técnico A clica em "Iniciar Atendimento" -> Alocação criada, técnico fica `EM_ATENDIMENTO` e OS fica `EM_ANDAMENTO`.
- [ ] Técnico B clica em "Entrar nesta OS" -> 2ª alocação criada; ambos aparecem trabalhando juntos na mesma OS.
- [ ] Técnico A pausa o atendimento -> Histórico de pausa registrado; Técnico B continua em atendimento normalmente.
- [ ] Técnico A retoma o atendimento -> Pausa encerrada com data/hora de retorno.
- [ ] Conclusão da OS:
  - Técnico A finaliza sua alocação -> OS continua `EM_ANDAMENTO` enquanto Técnico B está ativo.
  - Técnico B finaliza -> Sistema exige a **Foto da OS assinada pelo Líder** e o **Nome do Líder**.
  - Após envio, a OS muda para `CONCLUIDA` e ambos os técnicos voltam para `OCIOSO`.

### 4. Testes de Vínculo Emergencial (Sem OS Prévia)
- [ ] Técnico inicia atendimento de urgência direto no `/management/` (sem OS).
- [ ] Clica em "Vincular OS Física" no card do atendimento.
- [ ] Anexa foto e número da OS física -> Atendimento fica formalmente vinculado à OS.

### 5. Auditoria de Telas e Histórico
- [ ] Tela de Detalhes da OS (`/ordens-servico/<id>/`) exibe a Foto de Abertura e a Foto de Conclusão Assinada lado a lado.
- [ ] Tabela de mão de obra exibe o tempo líquido de cada técnico e o total da intervenção.
- [ ] Django Admin (`/admin/`) exibe todas as OSs com filtros, busca e inlines de alocações.

---

## 📦 Atualização Obrigatória do `Instrucoes.txt`
Ao concluir esta fase, registrar em `Instrucoes.txt`:
1. Resumo das novas rotas e views adicionadas.
2. Descrição do novo modelo `OrdemServico` e modificações no `Allocation`.
3. Variável de ambiente `GEMINI_API_KEY` e orientações de uso da IA.
4. Instruções de permissão dos grupos para o Portal de Módulos.
