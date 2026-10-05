# 🧠 SPEC — PASSAGEM DE TURNO ENTRE AS EQUIPES DO SETOR DE BLADDER

---

## 📌 1. CONTEXTO

- **URLs Envolvidas:**
  - `/bladder/operador/` (Chão de Fábrica — exibição das mensagens recebidas e botões de ação touch-friendly)
  - `/bladder/operador/fechar-turno/` (Fechamento do Turno — integração leve com mensagens criadas e acompanhamentos pendentes)
  - `/bladder/passagem-turno/` (Gestão / Histórico do Líder e consulta de cadeias de repasse)
  - `/bladder/passagem-turno/nova/` (Criação de mensagem geral ou vinculada à OP/Processo)
  - `/bladder/passagem-turno/<id>/acao/` (Ações: CIENTE, RESOLVIDO, REPASSAR)
- **Contextos:**
  - Operação de Chão de Fábrica no Tablet Industrial (visão limpa, compacta, sem poluição)
  - Fechamento formal do Turno
  - Painel de Gestão e Auditoria do Líder do Setor de Bladder
- **Perfis Afetados:**
  - Operador Bladder (Turma A e Turma B)
  - Funcionário de Apoio Bladder (autorizado)
  - Líder Bladder
  - Superusuário

---

## ❗ 2. PROBLEMA ATUAL

Hoje o setor de Bladder não possui um canal formal e auditável dentro do sistema para comunicação operacional entre as equipes que revezam na escala 12×36 (Turma A e Turma B).
Recados operacionais cruciais (como vazamento incipiente em prensa, separação de composto específico, atraso de matéria-prima ou instruções de setup para o próximo dia) correm o risco de se perder ou depender de anotações informais fora do sistema.
Além disso, a passagem de turno existente na Manutenção (`maintenance`) foi desenhada para outro fluxo (exportação para WhatsApp via Baileys), o que é incompatível com as regras de confidencialidade, normalização e controle interno do Chão de Fábrica do Bladder.

---

## 🎯 3. OBJETIVO

Implementar a funcionalidade formal e auditável de **Passagem de Turno do Setor de Bladder**, $100\%$ interna ao Django (sem dependência de WhatsApp, WebSockets ou chats genéricos), com:
1. Derivação automática do turno titular de origem e do próximo turno titular de destino através de `ConfiguracaoEscalaBladder` e `AjusteEscalaExcepcionalBladder`.
2. Sem seleção manual de turma, data ou operador destinatário no formulário.
3. Tipos conceituais de mensagens:
   - `INFORMATIVO`: Ação de `CIENTE` individual por operador.
   - `ACOMPANHAMENTO`: Ações de `CIENTE`, `RESOLVIDO` e `REPASSAR AO PRÓXIMO TURNO`.
4. Encadeamento imutável de repasses (cadeia A → B → A...), preservando histórico, autor original e usuário responsável por cada repasse até a resolução.
5. Vínculo operacional contextual opcional com Ordem de Produção (`OrdemProducaoBladder`), `ProcessoBladder`, `ProdutoBladder` e `Machine`.
6. Painel compacto e touch-friendly no Chão de Fábrica (`/bladder/operador/`) com ordenação de prioridade (Urgente → Importante → Normal) e sem quebra visual da tela de tablet.
7. Integração leve com a tela de Fechamento do Turno, sem afetar métricas, metas, realizados, pendências ou o Ledger de Produção.
8. Tela gerencial `/bladder/passagem-turno/` para consulta e auditoria pelo Líder Bladder.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos e Estruturas:
- `bladder/models.py`:
  - `MensagemPassagemTurnoBladder`
  - `AcaoMensagemTurnoBladder`
- `bladder/services.py`:
  - `calcular_proximo_turno_operacional(data_referencia)`
  - `criar_mensagem_passagem_turno(...)`
  - `registrar_ciencia_mensagem_turno(mensagem, user)`
  - `resolver_mensagem_acompanhamento(mensagem, user, observacao)`
  - `repassar_mensagem_acompanhamento(mensagem, user, observacao)`
  - `obter_mensagens_recebidas_turno(data_turno, turma, user)`
- `bladder/forms.py`:
  - `MensagemPassagemTurnoForm`
- `bladder/views.py`:
  - Atualização de `operador_turno` (injeção do painel de recados recebidos)
  - Atualização de `fechamento_turno` (seção de recados gerados e acompanhamentos abertos)
  - Nova view `passagem_turno_lista` (Líder / Histórico)
  - Nova view `criar_mensagem_turno_view` (Modal/POST)
  - Nova view `acao_mensagem_turno_view` (POST atômico para CIENTE, RESOLVIDO, REPASSAR)
- `bladder/urls.py`:
  - Novas rotas `passagem-turno/`, `passagem-turno/nova/`, `passagem-turno/<id>/acao/`
- `bladder/admin.py`:
  - Registro de `MensagemPassagemTurnoBladder` e `AcaoMensagemTurnoBladder` com filtros e inlines
- `bladder/templates/bladder/`:
  - `operador_turno.html` (painel superior expansível, badges, touch-buttons)
  - `fechamento_turno.html` (seção de recados do turno)
  - `passagem_turno_lista.html` (dashboard gerencial de recados e histórico da cadeia de repasse)
  - `includes/modal_mensagem_turno.html` (modal reutilizável de criação de recado)
- `bladder/tests.py`:
  - Suíte completa de testes automatizados cobrindo os 35+ requisitos especificados

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO criar novo app Django.
- ❌ NÃO criar chat em tempo real, WebSockets ou mensageiro privado.
- ❌ NÃO integrar com WhatsApp ou Baileys.
- ❌ NÃO alterar o app `maintenance` ou o `relatorio_turno` da manutenção.
- ❌ NÃO alterar OPs, quantidades planejadas, metas, realizados ou o status de produção.
- ❌ NÃO criar ou alterar `SaldoPendenteBladder`, `HistoricoProgramacaoBladder` ou o Ledger de produção.
- ❌ NÃO bloquear o fechamento do turno caso nenhum recado tenha sido criado.
- ❌ NÃO permitir edição destrutiva ou exclusão silenciosa de mensagens com histórico operacional.
- ❌ NÃO tocar no banco `scada`. Migrações e escritas estritamente no alias `default`.
- ❌ NÃO fazer deploy no servidor de produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION & SEGURANÇA)

1. **Permissões no Backend:**
   - Apenas `Operador Bladder` (ativo), `Funcionário de Apoio` (ativo), `Líder Bladder` e `Superusuário` podem criar ou interagir com recados.
   - Staff genérico ou usuários de outros módulos (`maintenance`, `production`, `matrizaria`) sem perfil Bladder são sumariamente bloqueados com HTTP 403 / redirect.
   - Validação estrita em todos os endpoints de backend.
2. **Escala 12×36 Alternada:**
   - Turma A e Turma B trabalham em dias alternados na mesma janela horária (06:00 às 18:00).
   - O cálculo do próximo turno operacional utiliza obrigatoriamente `ConfiguracaoEscalaBladder` e `AjusteEscalaExcepcionalBladder`. Se o dia subsequente for marcado como `FOLGA`, busca o próximo dia útil operacional com turma designada.
3. **Idempotência de Leitura (Ciência):**
   - Ciência registrada individualmente por usuário (`AcaoMensagemTurnoBladder`).
   - Evitar duplicidade de registros de `CIENTE` para o mesmo usuário na mesma mensagem (`unique_together` ou verificação segura).
4. **Isolamento de Banco:**
   - Banco SQLite e MySQL 100% compatíveis.
   - Sem migrations ou conexões com o alias `scada`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO DA PASSAGEM DE TURNO

### 7.1 Tipos e Fluxos:
- **INFORMATIVO:**
  - Recado comunicando um fato ou estado (ex: "Tarugos BLA004 deixados ao lado da extrusora").
  - Ação: `CIENTE`.
  - Uma vez ciente, o card diminui o destaque visual para aquele usuário e exibe badge discreto de ciência com timestamp, sem sumir do histórico.
- **ACOMPANHAMENTO:**
  - Recado sobre algo que requer atenção contínua ou ação (ex: "Prensa 01 apresentou ruído no fechamento; verificar temperatura de prato").
  - Ações:
    - `CIENTE`: Registra que o operador tomou conhecimento.
    - `RESOLVIDO`: Marca a mensagem como resolvida (`status = 'RESOLVIDA'`), registrando quem e quando resolveu, com observação opcional. Mantida no histórico.
    - `REPASSAR AO PRÓXIMO TURNO`: Não sobrescreve o destino original. Cria uma nova mensagem com status `ABERTA`, vinculada através de `mensagem_origem = mensagem_atual`, recalculando o próximo turno operacional de destino (cadeia A → B → A...). A mensagem anterior é marcada com `status = 'REPASSADA'` e registra ação de repasse.

### 7.2 Categorias:
- `PRODUCAO` ("Produção")
- `EQUIPAMENTO` ("Equipamento")
- `QUALIDADE` ("Qualidade")
- `MATERIAL` ("Material")
- `SEGURANCA` ("Segurança")
- `OUTRO` ("Outro")

### 7.3 Prioridades:
- `URGENTE` (vermelho/destaque alto)
- `IMPORTANTE` (âmbar/destaque médio)
- `NORMAL` (azul/cinza/neutro)
- Ordenação prioritária: Urgentes no topo, seguidos de Importantes e Normais.

### 7.4 Contexto Opcional da Mensagem:
- Pode ser geral (sem vínculos).
- Pode ser contextual a uma OP: ao clicar em `[ DEIXAR RECADO ]` no card da OP no Chão de Fábrica, preenche automaticamente OP, Processo, Máquina e Produto.

### 7.5 Funcionário de Apoio:
- Se autorizado e ativo no dia/horário, pode visualizar os recados do turno, registrar ciência, criar mensagens e atuar em acompanhamentos.
- A titularidade do turno permanece da turma oficial da escala (Turma A ou B), e o autor/responsável é o usuário real do apoio.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Turma de origem e destino calculadas automaticamente pela escala ativa e ajustes excepcionais.
- [ ] Formulário não solicita destinatário manual (turma, data ou usuário).
- [ ] Mensagens do tipo Informativo permitem marcar CIENTE individualmente por usuário.
- [ ] Ciência de um operador não marca automaticamente outro operador.
- [ ] O mesmo operador não gera duplo registro de CIENTE.
- [ ] Mensagens do tipo Acompanhamento permitem CIENTE, RESOLVER e REPASSAR.
- [ ] Repasse gera nova mensagem de continuidade apontando para o próximo turno da escala e vinculando a mensagem anterior (cadeia preservada).
- [ ] Resolução registra usuário e data/hora, mantendo imutabilidade do registro original.
- [ ] Criação a partir do card da OP preenche automaticamente o contexto operacional.
- [ ] Criação geral de recado disponível no Chão de Fábrica e no Fechamento.
- [ ] A funcionalidade não afeta OPs, saldos de produção, metas, realizados nem o Ledger.
- [ ] Seção "Passagem do Turno Anterior" em `/bladder/operador/` é responsiva e adaptada a tablets (touch-friendly, min 44px para botões, sem quebra de layout).
- [ ] Seção "Passagem para o Próximo Turno" no Fechamento exibe recados do dia e acompanhamentos abertos sem bloquear o fechamento.
- [ ] Tela `/bladder/passagem-turno/` para Líder permite filtrar por período, categoria, prioridade, status, máquina/processo e visualizar cadeia de repasse.
- [ ] Acesso restrito a Operadores Bladder, Apoios ativos, Líderes e Superusuários (Staff genérico e outros módulos bloqueados).
- [ ] Compatível com SQLite e MySQL; zero alterações no banco `scada`.
- [ ] Toda a suíte de testes do `bladder` e regressões de `maintenance` e `matrizaria` passam com 100% GREEN.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco 1: Confusão com escala de dias alternados (12x36).**
  - *Mitigação:* Usar rigorosamente o serviço `calcular_proximo_turno_operacional` baseado em `ConfiguracaoEscalaBladder` e `AjusteEscalaExcepcionalBladder`, testando cenários normais e com ajustes excepcionais/folgas.
- **Risco 2: Poluição visual no tablet do Chão de Fábrica.**
  - *Mitigação:* Painel retrátil/compacto no topo com contador (`PASSAGEM DO TURNO ANTERIOR — X RECADOS`), destaque para urgentes e recados já reconhecidos pelo usuário recolhidos ou esmaecidos.
- **Risco 3: Interrupção indevida do Fechamento do Turno.**
  - *Mitigação:* A seção no fechamento é meramente informativa e de conveniência. Se não houver recados a repassar ou registrar, o fechamento ocorre normalmente com zero impacto no Ledger de produção.
- **Risco 4: Duplo Ciente ou concorrência de leitura.**
  - *Mitigação:* Criação de ciência atômica com `get_or_create` ou `unique_together` em `(mensagem, usuario, acao='CIENTE')`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Fase A — Auditoria & SPEC** (Concluída nesta etapa)
2. **Fase B — Persistência e Models**:
   - Model `MensagemPassagemTurnoBladder` e `AcaoMensagemTurnoBladder`.
   - Django Admin e migrations aditivas no app `bladder`.
3. **Fase C — Camada de Serviços**:
   - Centralizar regras em `bladder/services.py` (`calcular_proximo_turno_operacional`, criação, ciente, resolver, repassar, listagem de recados).
4. **Fase D — Chão de Fábrica (Tablet)**:
   - Integrar painel de recados em `/bladder/operador/`.
   - Botão geral de recado e botão contextual no card da OP.
   - Modais touch-friendly para leitura rápida e ações.
5. **Fase E — Fechamento do Turno**:
   - Adicionar seção leve no template `fechamento_turno.html` com recados criados e acompanhamentos abertos.
6. **Fase F — Painel do Líder e Histórico**:
   - Rota `/bladder/passagem-turno/`, filtros por período/categoria/prioridade/status e visualização da cadeia de repasse.
7. **Fase G — Segurança, QA e Regressão Geral**:
   - Testes unitários e de integração com cenários canônicos (A → B → A, apoio, permissões, tablet).

---

## 🧪 11. TESTES OBRIGATÓRIOS

1. Turma A cria mensagem e destino calculado é o próximo turno correto (Turma B).
2. Turma B recebe automaticamente ao abrir Chão de Fábrica.
3. Ajuste excepcional de escala (troca de turma ou folga) é estritamente respeitado no cálculo de destino.
4. Operador não seleciona destinatário manual.
5. Autor é registrado automaticamente (`request.user`).
6. Mensagem Informativa permite ação CIENTE.
7. Ciência de João não marca Maria como ciente.
8. Mesmo usuário não duplica ciência.
9. Mensagem de Acompanhamento permite RESOLVIDO.
10. Resolução registra usuário e data/hora no histórico.
11. Mensagem de Acompanhamento permite REPASSAR.
12. Repasse cria nova mensagem de continuidade preservando a origem anterior.
13. Repasse calcula corretamente o próximo turno da escala (A → B → A).
14. Mensagem original não é alterada destrutivamente.
15. Vínculo contextual com OP preenche processo, máquina e produto.
16. Mensagem sem OP (geral) funciona normalmente.
17. Mensagem não altera OP, meta, realizado nem saldo remanescente.
18. Mensagem não cria SaldoPendenteBladder nem afeta Ledger de produção.
19. Funcionário de Apoio autorizado visualiza, cria e dá ciência aos recados do turno.
20. Funcionário de Apoio não se torna Turma A/B (titularidade preservada).
21. Líder visualiza histórico completo e filtros.
22. Bloqueio estrito para operadores de outros módulos (Manutenção, Matrizaria, Produção).
23. Bloqueio estrito para usuário staff genérico sem perfil Bladder.
24. Superusuário acessa normalmente.
25. URLs de ação direta são protegidas contra CSRF e validação backend.
26. Mensagem resolvida permanece no histórico.
27. Filtros por período, categoria e prioridade funcionam.
28. Prioridade Urgente é ordenada antes da Normal.
29. Cenário Integrado Completo (Dia 1 Turma A -> Dia 2 Turma B repassa -> Dia 3 Turma A resolve).
30. Fechamento de turno funciona independentemente da existência ou ausência de recados.
