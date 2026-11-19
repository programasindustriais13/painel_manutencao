# 🧠 SPEC — EVOLUÇÃO OPERACIONAL DE TURNOS, MODO NOTURNO E MANUSEIO NO BLADDER

Data: 18/11/2026  
Status: **HOMOLOGADO E APROVADO PELO SUBAGENTE QA (100% DOS TESTES APROVADOS)**  
Abordagem: **SPEC-DRIVEN** estrita, conforme `constitution.md` e `regras_programacao/SPEC_TEMPLATE.md`.

---

## 📌 1. CONTEXTO

O presente documento normatiza a evolução operacional do chão de fábrica para o módulo `bladder` do **Painel de Manutenção Industrial**, abrangendo a jornada completa dos operadores de máquina, operadores de apoio, retiradas no turno noturno e liderança de produção.

- **URLs Envolvidas:**
  - `/bladder/operador/` (Quadro Operacional do Turno — Tablet de Chão de Fábrica, Tema Claro).
  - `/bladder/operador/fechar-turno/` (Fechamento Formal e Único do Turno Operacional).
  - `/bladder/operador/extrusoes/<int:pk>/manuseio/` (Formulário de Execução/Retomada de Manuseio de Tarugos).
  - `/bladder/noturno/` (NOVO — Estação Restrita de Retiradas Noturnas com leitor USB).
  - `/bladder/noturno/ativar/` (NOVO — Ativação auditada do período noturno e encerramento da sessão diurna).
  - `/bladder/noturno/retirar/` (NOVO — Submissão atômica de saída de estoque por leitor USB / teclado).
  - `/bladder/noturno/encerrar/` (NOVO — Login integrado do operador diurno na própria tela noturna).
  - `/bladder/bem-vindo/` (NOVO — Tela de Boas-Vindas contextual com dados reais do turno e OPs).
  - `/login/`, `/redirect/` (`home_redirect`) e `/portal/` (`portal_select`) (Roteamento inteligente pós-login).
- **Contextos do Sistema:**
  - Terminal de chão de fábrica em tablet industrial (Touchscreen 10", leitores USB, navegação simplificada).
  - Estação noturna de almoxarifado/vulcanização (retirada ágil de bladders sem operador dedicado de bladder).
  - Hub de módulos e controle de sessão por perfil (`maintenance/middleware.py`).
- **Perfis e Identidades Afetados:**
  - `Operadores Bladder` (Turma A e Turma B na escala 12×36, 06:00 às 18:00).
  - `Funcionário de Apoio Bladder` (apoio operacional escalado para o dia).
  - `Turno Noturno Bladder` (identidade restrita do Django para retiradas noturnas, sem acesso administrativo).
  - `Liderança Bladder` (Líder de Produção / PCP).

---

## ❗ 2. PROBLEMA ATUAL E DIAGNÓSTICO DO ARQUITETO

### 2.1 Manuseio Rígido e Impossibilidade de Transferência entre Turnos (Entrega A)
- **Cenário atual:** O processo de Manuseio de Tarugos (Código `06`) é dependente de uma execução prévia de Extrusão de Bladder (Código `03`). Quando a extrusão é registrada, ela gera uma pendência de manuseio (`extrusao.manuseio__isnull=True`). No entanto, o manuseio atual é binário: ou o operador manuseia toda a quantidade e salva com situação fixa `CONCLUIDA`, ou o registro fica pendente integralmente.
- **Lacuna operacional:** Se uma extrusão registrar 120 tarugos e o operador conseguir manusear apenas 50 tarugos até as 18:00 (término do seu turno), não há como registrar o manuseio parcial preservando as medições já efetuadas e repassar formalmente os 70 tarugos restantes para a próxima turma.
- **Risco de distorção:** No fechamento de turno (`fechamento_turno.html`), se houver manuseios incompletos, não há controle de encaminhamento entre turmas, correndo o risco de duplicar ordens de produção ou perder a rastreabilidade das amostras (diâmetro, comprimento e peso).

### 2.2 Retiradas Noturnas sem Operador e Risco de Timeout (Entrega B)
- **Cenário atual:** O setor de Bladder não possui equipe de extrusão/manuseio no período noturno (18:00 às 06:00). Porém, os operadores de Vulcanização de Pneus precisam retirar Bladders acabados do estoque para abastecer as prensas.
- **Falha de sessão:** O middleware de sessão humana (`SessionExpiryByProfileMiddleware`) encerra qualquer sessão inativa após **5 minutos** (`INACTIVITY_TIMEOUT_SECONDS = 300`). Isso inviabiliza deixar um tablet na fábrica para retiradas esporádicas durante a madrugada.
- **Falha de UX e Segurança:** Se uma conta comum ficasse logada, o operador noturno teria acesso indevido a fechar turno, apontar extrusão, excluir registros ou acessar outros módulos. Além disso, as leituras de código de barras via leitor USB emulam teclado e disparam `Enter` ao final; na interface web padrão, esse `Enter` submete o formulário prematuramente antes de digitar a quantidade de volumes.

### 2.3 Ausência de Transição e Boas-Vindas Contextual (Entrega C)
- **Cenário atual:** Ao efetuar login às 05:50 da manhã, o operador diurno é jogado bruscamente na tela de lista de OPs (`/bladder/operador/`), sem uma visão panorâmica de recepção que mostre a turma do dia, as OPs prioritárias, os manuseios recebidos da turma anterior e os recados urgentes da passagem de turno.
- **Problema de roteamento:** Falta um mecanismo na sessão (`bladder_welcome_seen`) que exiba essa recepção de forma elegante no primeiro acesso do dia/sessão, sem ficar reaparecendo a cada F5 ou navegação entre abas.

### 2.4 Ilegibilidade Crítica no Fechamento de Turno (Entrega D)
- **Cenário atual:** A tela `/bladder/operador/fechar-turno/` é renderizada com `theme_class: 'theme-light'`. No entanto, seu HTML utiliza internamente dezenas de classes do tema escuro: `bg-black bg-opacity-50`, `bg-black bg-opacity-40`, `table-dark` e `text-light`.
- **Falha grave de contraste (WCAG AA):** A folha de estilos `base_bladder.html` possui a regra:
  ```css
  body.theme-light .text-light { color: #0F172A !important; }
  ```
  Isso transforma qualquer texto com classe `.text-light` na cor **preta/quase preta** (`#0F172A`). Quando esse texto escuro é colocado sobre um container escuro (`bg-black bg-opacity-50`), o contraste cai para **1.2:1**, tornando o texto completamente invisível no tablet em ambiente fabril iluminado. Além disso, labels com `btn-outline-warning` sobre fundos brancos possuem contraste inferior a 2.5:1.

---

## 🎯 3. OBJETIVO GERAL

Estruturar e normatizar no app Django existente `bladder` uma evolução integrada, segura e auditável:
1. **Entrega A (Manuseio Parcial e Transferência Seletiva):** Permitir salvar execuções parciais de manuseio de tarugos com acumulação rastreada, medições parciais preservadas e transferência formal selecionada no fechamento para a próxima turma.
2. **Entrega B (Estação de Retirada Noturna com Leitor USB):** Criar a identidade restrita `Turno Noturno Bladder`, ativação auditada de período noturno, sessão tolerante a inatividade (com teto absoluto de 16h), tela dedicada com apenas 3 campos (Modelo, Lote USB com zeros à esquerda, Volume), proteção contra Enter do barcode scanner, baixa atômica de estoque integrada à DR-201 e transição para o turno diurno com login integrado.
3. **Entrega C (Tela de Boas-Vindas Contextual):** Criar a tela `/bladder/bem-vindo/` com saudação dinâmica por turno/horário, resumo das OPs do dia, manuseios recebidos, alertas de passagem de turno e roteamento inteligente sem loop de redirecionamento.
4. **Entrega D (Correção de Contraste e Responsividade WCAG AA):** Refatorar classes e CSS de `fechamento_turno.html` para tema claro puro, alto contraste (mínimo 4.5:1 para texto normal e 3:1 para elementos de interface), eliminando containers pretos em tema claro e garantindo legibilidade em 375px, 768px e 1366px.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Módulos e Arquivos Afetados:
- `bladder/models.py`:
  - Adição de campos em `ApontamentoTurnoBladder` (`quantidade_manuseada`, `status_manuseio`).
  - Criação do modelo `TransferenciaManuseioBladder` (auditoria do encaminhamento entre turmas).
  - Criação do modelo `SessaoNoturnaBladder` (auditoria de ativação, retiradas e encerramento do turno noturno).
- `bladder/services.py`:
  - Evolução do serviço `executar_fechamento_turno` para validar manuseios incompletos e persistir transferências seletivas.
  - Funções de serviço para manuseio parcial e retomada (`registrar_manuseio_parcial`, `retomar_manuseio_recebido`).
  - Funções de ativação e encerramento da sessão noturna (`ativar_estacao_noturna`, `encerrar_estacao_noturna`).
  - Função de saída de estoque noturna baseada em `registrar_movimentacao_multipla_estoque` com idempotência.
- `bladder/producao.py` e `bladder/forms_producao.py`:
  - Suporte ao formulário de manuseio com ações `SALVAR PARCIAL` e `CONCLUIR MANUSEIO`.
  - Tratamento de formset de amostras parciais e cálculo ponderado/incremental de médias.
- `bladder/views.py` e `bladder/views_producao.py`:
  - Views de estação noturna (`estacao_noturna_view`, `estacao_noturna_ativar`, `estacao_noturna_retirar`, `estacao_noturna_encerrar`).
  - View de boas-vindas (`boas_vindas_view`).
  - Ajustes em `operador_turno` para exibir "MANUSEIOS RECEBIDOS DO TURNO ANTERIOR".
  - Ajustes em `fechamento_turno` para listar manuseios pendentes e processar checkboxes de encaminhamento.
- `bladder/decorators.py`:
  - Decorators e validações de rota para isolamento estrito do usuário noturno.
- `bladder/urls.py`:
  - Registro das novas rotas de modo noturno e boas-vindas.
- `maintenance/middleware.py`:
  - Suporte à sessão do Turno Noturno em `SessionExpiryByProfileMiddleware` (isenção dos 5 minutos, teto de 16h e bloqueio de rotas).
- `maintenance/views.py`:
  - Ajuste de `home_redirect` e `portal_select` para rotear operador/líder Bladder via tela de boas-vindas no primeiro acesso.
- `bladder/templates/bladder/`:
  - `fechamento_turno.html` (refatoração de contraste WCAG AA e seção de encaminhamento de manuseios).
  - `operador_turno.html` (seção de manuseios recebidos e botão de ativação do período noturno).
  - `producao_form.html` (botões "SALVAR PARCIAL" vs "CONCLUIR MANUSEIO").
  - `noturno_estacao.html` (NOVO — Interface simplificada de 3 campos com leitor USB).
  - `bem_vindo.html` (NOVO — Dashboard de recepção do operador).
  - `base_bladder.html` (ajustes de regras CSS de tema claro e alto contraste).

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não alterar a lógica dos módulos `maintenance`, `matrizaria` ou `production`, exceto pelas regras estritas de middleware e roteamento de login geral em `maintenance`.
- ❌ Não modificar nem gravar dados na base SCADA (`using='scada'`). Todo o armazenamento deve residir na base `default`.
- ❌ Não duplicar Ordens de Produção (OPs). O manuseio de tarugos permanece estritamente vinculado à OP de extrusão correspondente.
- ❌ Não contabilizar peças manuseadas como produção adicional no dashboard de indicadores. Produção é registrada na Extrusão (`03`) ou Prensas (`01`/`02`).
- ❌ Não realizar migrações destrutivas de banco (`DROP COLUMN`, `DROP TABLE`).
- ❌ Não remover a trava de estoque negativo nem desabilitar a idempotência de sincronização da planilha DR-201.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION & SEGURANÇA)

1. **Execução Controlada:** Apenas um ambiente virtual `.venv`, um projeto Django e compatibilidade rigorosa entre **SQLite** (desenvolvimento local) e **MySQL** (produção).
2. **Autorização Central no Backend:** NUNCA confiar em validações de frontend. Todas as rotas operacionais e de estoque devem verificar:
   - Usuário autenticado e ativo.
   - Perfil operacional ou papel de apoio válido para a data da escala.
   - Usuário noturno confinado exclusivamente às rotas noturnas.
3. **Integridade de Estoque:** Nenhuma saída pode deixar o saldo físico menor que zero (`saldo_anterior - quantidade >= 0`).
4. **Idempotência Estrita:** Submissões por formulário web ou leitor de código de barras USB devem utilizar chave de idempotência (`UUIDField` / `CharField(64)`), impedindo duplicidade caso o leitor emita múltiplos disparos ou o operador clique repetidas vezes.

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS POR ENTREGA

### 7.1 ENTREGA A — Manuseio Parcial e Transferência Seletiva entre Turnos

```
[Extrusão #03 Salva] ──▶ Libera Manuseio (Qtd Total Extrusada)
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   [Salvar Parcial]                      [Concluir Manuseio]
   - Qtd Manuseada < Total               - Qtd Manuseada == Total
   - Amostras Parciais Salvas            - Todas Amostras Salvas
   - Status: PARCIAL                     - Status: CONCLUÍDO
            │
            ▼ (Fim de Turno / Fechamento)
   [Fechamento do Turno]
   - Lista manuseios incompletos (Pendente / Parcial)
   - Seleção com Checkboxes para encaminhamento
   - Registro em TransferenciaManuseioBladder
            │
            ▼
   [Próximo Turno Assume]
   - Quadro Operacional: Seção "MANUSEIOS RECEBIDOS"
   - Ação "RETOMAR MANUSEIO"
   - Continua a mesma OP e Extrusão até a conclusão
```

#### Estados Operacionais do Manuseio:
- `PENDENTE`: Extrusão realizada e apontada com sucesso; manuseio ainda não iniciado.
- `PARCIAL`: Operador iniciou o manuseio, conferiu parte dos tarugos, coletou as amostras correspondentes àquela parcela e clicou em **"SALVAR PARCIAL"**.
- `CONCLUIDO`: Toda a quantidade extrusada foi manuseada e o lote total de amostras foi validado.

#### Regras de Quantidades e Amostragem:
- A quantidade manuseada não pode ser superior à quantidade extrusada: `0 <= quantidade_manuseada <= extrusao.quantidade_realizada`.
- Quantidade restante: `quantidade_restante = max(0, extrusao.quantidade_realizada - quantidade_manuseada)`.
- **Amostragem Ponderada/Incremental:** A regra normativa de amostragem exige `ceil(quantidade_total / 10)` amostras.
  - Ao salvar parcial, exige-se no mínimo as amostras proporcionais à quantidade já manuseada: `ceil(quantidade_manuseada / 10)`.
  - Ao retomar no turno seguinte, as amostras já salvas são mantidas imutáveis no banco e exibidas preenchidas; o novo operador insere apenas as amostras complementares até atingir a meta final da extrusão.
  - As médias de diâmetro, comprimento e peso são recalculadas considerando o conjunto completo de amostras salvas.

#### Validação no Fechamento de Turno:
- Na tela `/bladder/operador/fechar-turno/`:
  - Seção: **"Manuseios Pendentes e Parciais do Turno"**.
  - Exibe cada extrusão do dia que não esteja com manuseio `CONCLUIDO`.
  - Checkbox obrigatório de encaminhamento: o operador deve marcar os manuseios a serem transferidos para o próximo turno.
  - **Bloqueio de Inconsistência:** Se houver manuseio em estado `PARCIAL` ou `PENDENTE` originado no turno que não seja selecionado para encaminhamento e nem esteja concluído, o fechamento deve barrar a submissão com alerta claro: *"Existem manuseios incompletos neste turno. Selecione o encaminhamento para o próximo turno antes de confirmar o fechamento."*
  - Ao confirmar o fechamento, cria-se o registro em `TransferenciaManuseioBladder` com status `ENCAMINHADO`.

#### Quadro do Próximo Turno:
- Na view `operador_turno` (`/bladder/operador/`), para a nova turma que inicia:
  - Seção destacada: **"MANUSEIOS RECEBIDOS DO TURNO ANTERIOR"**.
  - Exibe: Número curto da OP, Modelo/Medida, Turma e Operador de origem, Quantidade já manuseada vs Restante, Observações da passagem.
  - Botão de ação: **"RETOMAR MANUSEIO"** -> abre `/bladder/operador/extrusoes/<id>/manuseio/` com dados já carregados para continuidade.

---

### 7.2 ENTREGA B — Modo Noturno: Estação de Retirada com Leitor USB

```
[Operador Diurno] ──▶ Clica em "INICIAR PERÍODO NOTURNO"
                             │
                             ▼ (Confirmação e Auditoria)
                    [Sessão Noturna Ativada]
                    - Logout Diurno seguro
                    - Login autêntico: noturno_bladder
                    - Middleware: sem timeout de 5 min (teto 16h)
                    - Restrição: acessa SOMENTE /bladder/noturno/
                             │
                             ▼
              [Tela Noturna: Apenas 3 Campos]
              1. Modelo (Select ProdutoBladder com Saldo)
              2. Lote (Leitor USB / Teclado com Zeros à Esquerda)
                 * Enter do Leitor NÃO submete form, foca no Volume
              3. Volume (Manual, Inteiro > 0, Validado <= Saldo)
                             │
                             ▼ Clica em "CONFIRMAR SAÍDA DO ESTOQUE"
              [Baixa Atômica de Estoque]
              - MovimentacaoEstoqueBladder (SAIDA)
              - 1 Movimento = 1 Lote + N Volumes = 1 Linha DR-201
              - Histórico da Sessão atualizado na tela
                             │
                             ▼ (Ao amanhecer às 06:00)
              [Botão "INICIAR TURNO DIURNO"]
              - Modal na própria tela pede Usuário + Senha Diurno
              - Sucesso: Fecha sessão noturna, Loga Diurno, vai para Boas-Vindas
              - Falha: Erro na modal, mantém tela noturna segura
```

#### Identidade e Credenciais:
- Usuário Django dedicado: `noturno_bladder`.
- Nome de exibição: `Turno Noturno Bladder`.
- Permissões: sem `is_staff`, sem `is_superuser`, restrito a grupo operacional de saídas noturnas. Não possui acesso a dashboards, cadastros ou fechamento de turno.

#### Ciclo da Sessão no Middleware (`SessionExpiryByProfileMiddleware`):
- O middleware identifica `is_night_shift_account(user, request)`:
  - Não aplica o logout por inatividade humana de 5 minutos.
  - Valida o teto absoluto: `elapsed = now_ts - session.get('night_shift_start_ts')`. Se `elapsed > 16 * 3600` (16 horas), expira a sessão noturna por segurança e desautentica.
  - **Restrição Estrita de URL:** Se `is_night_shift_account` for verdadeiro e a rota solicitada não pertencer ao prefixo `/bladder/noturno/`, `/static/` ou `/logout/`, o middleware intercepta a requisição e redireciona imediatamente para `/bladder/noturno/`, impedindo qualquer tentativa de bisbilhotar o restante do sistema.

#### Interface e Leitor USB:
- O leitor de código de barras USB funciona em modo HID (emulação de teclado). Ao escanear a etiqueta do Bladder, ele digita a sequência de caracteres e finaliza emitindo `\n` ou `\r` (tecla Enter).
- **Proteção contra disparo acidental:** O JavaScript da tela noturna captura o evento `keydown` no campo `#input-lote`:
  ```javascript
  if (e.key === "Enter") {
      e.preventDefault();
      document.getElementById("input-volume").focus();
      document.getElementById("input-volume").select();
  }
  ```
- **Preservação de Zeros à Esquerda:** O valor do lote deve ser tratado rigorosamente como string (`CharField`), sanitizado sem conversão numérica (ex: `"000524"` não pode virar `524`).
- **Validação de Volume:** O volume deve ser preenchido manualmente pelo operador que está retirando as peças, sendo um inteiro `> 0` e `<= saldo_atual_produto`.

#### Transição Segura para o Turno Diurno:
- A tela noturna exibe no topo o botão destacado **"INICIAR TURNO DIURNO"**.
- Ao clicar, abre modal nativo na própria tela contendo campos:
  - `Nome de Usuário`
  - `Senha`
- A submissão valida no backend via `authenticate(username=..., password=...)`.
- Se as credenciais forem válidas e o usuário pertencer ao setor de Bladder:
  - Atualiza o registro de auditoria `SessaoNoturnaBladder` com data de encerramento e usuário que assumiu.
  - Efetua `django.contrib.auth.login(request, user_diurno)`.
  - Reinicia o relógio de inatividade humana no padrão de 5 minutos.
  - Limpa as chaves da sessão noturna.
  - Configura `request.session['bladder_welcome_seen'] = False`.
  - Redireciona para `/bladder/bem-vindo/`.
- Se falhar: a modal permanece aberta com mensagem de erro clara em vermelho ("Credenciais inválidas ou usuário sem permissão no Bladder"), sem recarregar a página e sem derrubar a estação noturna.

---

### 7.3 ENTREGA C — Tela de Boas-Vindas Contextual

```
[Login do Operador / Líder Bladder]
                 │
                 ▼
[home_redirect / portal_select]
- Verifica request.session.get('bladder_welcome_seen')
- Se False/None ──▶ Redireciona para /bladder/bem-vindo/
                 │
                 ▼
     [Tela de Boas-Vindas]
     - Saudação contextual ("BOM DIA, MARCOS!")
     - Data, Escala e Turma do Dia
     - Resumo de OPs programadas e Metas
     - Manuseios Recebidos do Turno Anterior
     - Recados não lidos / urgentes
     - Marca session['bladder_welcome_seen'] = True
                 │
                 ▼
     [Ação: "IR PARA O TURNO"] ──▶ /bladder/operador/
     (F5 ou navegações posteriores vão direto ao turno)
```

#### Regras da Saudação Contextual:
- Baseada no horário local de Brasília (`timezone.localtime()`):
  - `05:00` às `11:59`: `"BOM DIA, [NOME]!"`
  - `12:00` às `17:59`: `"BOA TARDE, [NOME]!"`
  - `18:00` às `04:59`: `"BOA NOITE, [NOME]!"`
- Exibição destacada da **Turma Titular do Dia** (conforme `ConfiguracaoEscalaBladder` e eventuais ajustes) e se o usuário está atuando como Titular, Apoio ou Liderança.

#### Informações Consolidadas do Turno:
1. **Ordens de Produção do Dia:** Total de OPs programadas, soma total de peças planejadas e gráfico/barra de progresso inicial (0% no início do dia).
2. **Manuseios Transferidos:** Alerta visível caso existam tarugos aguardando manuseio transferidos pelo turno anterior.
3. **Passagem de Turno:** Notificações de recados não lidos, informativos recentes e acompanhamentos abertos.
4. **Alerta Semafórico de Estoque:** Indicação rápida de modelos em situação Crítica ou Atenção.

#### Navegação e Sessão:
- Botão primário amplo (min-height 52px): **"IR PARA O TURNO"** -> navega para `/bladder/operador/`.
- Botão secundário (apenas para quem tem `user_is_lider_bladder`): **"IR PARA GESTÃO / DASHBOARD"** -> navega para `/bladder/`.
- A flag `request.session['bladder_welcome_seen'] = True` garante que o usuário não seja redirecionado repetidamente para a tela de boas-vindas a cada navegação de rotina durante o seu expediente.

---

### 7.4 ENTREGA D — Correção de Contraste e Responsividade (WCAG AA)

#### Matriz de Contraste — Antes vs Depois:

| Elemento em `fechamento_turno.html` | Implementação Anterior (Incorreta) | Problema de Contraste | Correção Normativa (Tema Claro WCAG AA) | Razão de Contraste Resultante |
|---|---|---|---|---|
| Card individual da OP | `bg-black bg-opacity-50` com borda escura | Fundo quase preto em página com body branco | `.op-card-board` com fundo `#FFFFFF`, borda `#CBD5E1` e sombra suave | > 12:1 contra texto `#0F172A` |
| Nome do Produto e Medida | `.text-light` dentro de `bg-black` | CSS força `.text-light` para `#0F172A` (preto sobre preto) | Classe explícita `.text-slate-900` com peso 700 sobre fundo branco | > 14:1 (Passa WCAG AAA) |
| Meta e Valores Numéricos | `text-light font-monospace` | Texto escuro sobre container translúcido escuro | Fundo de destaque `#F8FAFC`, borda `#E2E8F0`, texto `#0F172A` | > 12:1 |
| Input Quantidade Realizada | Fundo escuro com borda tênue | Ilegível sob luz natural em tablet de fábrica | Fundo `#FFFFFF`, borda `#94A3B8`, texto `#0F172A` em JetBrains Mono | > 11:1 |
| Bloco de Déficit de Produção | `bg-danger bg-opacity-10 border-danger` com labels `.text-light` | Labels pretas sobre fundo avermelhado escuro | Fundo `#FEF2F2`, borda `#F87171`, título `#991B1B`, labels `#1E293B` | > 7:1 (Passa WCAG AAA) |
| Checkboxes de Categoria de Desvio | `btn-outline-warning` | Amarelo sobre fundo branco/claro (contraste < 2.5:1) | Botões `btn-check` com borda `#94A3B8`, texto `#1E293B` não selecionado e fundo âmbar `#D97706` com texto branco `#FFFFFF` selecionado | > 4.8:1 (Passa WCAG AA) |
| Resumo de Movimentações / Passagem | `bg-black bg-opacity-20` | Caixas escuras soltas no layout claro | Cards brancos estruturados com cabeçalho cinza `#F1F5F9` | > 10:1 |
| Tabela de Turno Já Encerrado | `table-dark` com `text-light` | Conflito de regras `body.theme-light .table-dark td` | Tabela nativa clara com cabeçalho `#F1F5F9`, linhas zebradas `#FFFFFF` e texto `#0F172A` | > 10:1 |

#### Breakpoints Responsivos Obrigatórios:
- **Mobile (375px):** Empilhamento vertical de colunas (meta, quantidade realizada e resultado), botões touch em largura integral (`w-100`, min-height 48px), eliminação de scroll horizontal acidental.
- **Tablet Industrial (768px - 1024px):** Layout em grade de 2 colunas para inputs e métricas, alvos de toque amplos para dedos com luvas industriais.
- **Desktop (1366px+):** Layout de alta densidade informativa com container centralizado de largura máxima de 1140px.

---

## 🗄️ 8. MODELAGEM DE DADOS DETALHADA

### 8.1 Alterações em Modelos Existentes (`bladder/models.py`)

#### Ampliação de `ApontamentoTurnoBladder`:
```python
# Novos campos em ApontamentoTurnoBladder (com null=True/blank=True ou default para compatibilidade SQLite/MySQL):
quantidade_manuseada = models.PositiveIntegerField(
    default=0,
    verbose_name="Quantidade Manuseada (un)",
    help_text="Quantidade de tarugos efetivamente manuseados nesta etapa"
)

status_manuseio = models.CharField(
    max_length=20,
    choices=[
        ('PENDENTE', 'Pendente'),
        ('PARCIAL', 'Manuseio Parcial'),
        ('CONCLUIDO', 'Manuseio Concluído'),
    ],
    default='PENDENTE',
    db_index=True,
    verbose_name="Status do Manuseio"
)
```

### 8.2 Novos Modelos Normativos

#### Modelo `TransferenciaManuseioBladder`:
Registra a passagem formal e auditável de tarugos pendentes/parciais entre as equipes de revezamento.
```python
class TransferenciaManuseioBladder(models.Model):
    """
    Rastreabilidade e auditoria da transferência de manuseios de tarugos
    incompletos (parciais ou pendentes) entre turnos de produção.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
    ]
    STATUS_CHOICES = [
        ('ENCAMINHADO', 'Encaminhado ao Próximo Turno'),
        ('RETOMADO', 'Retomado pela Equipe de Destino'),
        ('CONCLUIDO', 'Concluído no Destino'),
        ('CANCELADO', 'Cancelado pela Liderança'),
    ]

    extrusao = models.ForeignKey(
        'ApontamentoTurnoBladder',
        on_delete=models.PROTECT,
        related_name='transferencias_manuseio',
        verbose_name="Execução de Extrusão de Origem"
    )
    apontamento_manuseio = models.ForeignKey(
        'ApontamentoTurnoBladder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transferencias_origem',
        verbose_name="Apontamento de Manuseio Parcial Vinculado"
    )
    fechamento_origem = models.ForeignKey(
        'FechamentoTurnoBladder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manuseios_transferidos',
        verbose_name="Fechamento de Origem"
    )
    turma_origem = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma de Origem")
    turma_destino = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma de Destino")
    data_turno_origem = models.DateField(db_index=True, verbose_name="Data do Turno de Origem")
    data_turno_destino = models.DateField(db_index=True, verbose_name="Data do Turno de Destino")
    
    operador_transferiu = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='manuseios_transferidos_enviados',
        verbose_name="Operador que Transferiu"
    )
    quantidade_extrusada = models.PositiveIntegerField(verbose_name="Quantidade Total Extrusada")
    quantidade_acumulada_manuseada = models.PositiveIntegerField(default=0, verbose_name="Qtd Já Manuseada")
    quantidade_restante = models.PositiveIntegerField(verbose_name="Qtd Restante a Manusear")

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ENCAMINHADO',
        db_index=True,
        verbose_name="Status da Transferência"
    )
    operador_retomou = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manuseios_transferidos_retomados',
        verbose_name="Operador que Retomou"
    )
    data_retomada = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora da Retomada")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações do Encaminhamento")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transferência de Manuseio entre Turnos"
        verbose_name_plural = "Transferências de Manuseios entre Turnos"
        ordering = ['-created_at']

    def __str__(self):
        return f"Transferência Extrusão #{self.extrusao_id}: {self.turma_origem} -> {self.turma_destino} ({self.quantidade_restante} un restantes)"
```

#### Modelo `SessaoNoturnaBladder`:
Registra a auditoria formal do período noturno, ativador, saídas associadas e encerramento.
```python
class SessaoNoturnaBladder(models.Model):
    """
    Auditoria e rastreamento de cada sessão de Estação Noturna de Retiradas.
    Permite auditar quem ativou, o período de vigência e o operador diurno que assumiu o posto.
    """
    STATUS_CHOICES = [
        ('ATIVA', 'Estação Noturna Ativa'),
        ('ENCERRADA', 'Encerrada pelo Turno Diurno'),
        ('EXPIRADA', 'Expirada Automaticamente por Teto'),
    ]

    operador_ativou = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='sessoes_noturnas_ativadas',
        verbose_name="Operador Diurno que Ativou"
    )
    data_hora_inicio = models.DateTimeField(default=timezone.now, verbose_name="Início da Sessão Noturna")
    data_hora_fim = models.DateTimeField(null=True, blank=True, verbose_name="Término da Sessão Noturna")
    operador_encerrou = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessoes_noturnas_encerradas',
        verbose_name="Operador Diurno que Encerrou"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ATIVA', db_index=True)
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sessão Noturna de Retiradas"
        verbose_name_plural = "Sessões Noturnas de Retiradas"
        ordering = ['-data_hora_inicio']

    def __str__(self):
        return f"Sessão Noturna #{self.id} em {self.data_hora_inicio.strftime('%d/%m/%Y %H:%M')} [{self.get_status_display()}]"
```

---

## 🧪 9. CRITÉRIOS DE ACEITAÇÃO

A implementação das 4 entregas será aprovada se, e somente se, satisfizer todos os critérios abaixo:

### Entrega A — Manuseio Parcial e Transferência Seletiva:
- [ ] No formulário de manuseio (`producao_form.html` com código `06`), é possível registrar quantidade manuseada inferior à quantidade extrusada e clicar em **"SALVAR PARCIAL"**.
- [ ] O apontamento de manuseio é gravado com `status_manuseio = 'PARCIAL'` e as medições de amostras já digitadas são salvas no banco `default` sem perdas.
- [ ] No fechamento de turno (`/bladder/operador/fechar-turno/`), os manuseios incompletos (pendentes ou parciais) aparecem em seção dedicada com checkboxes de seleção.
- [ ] A tentativa de fechar o turno com manuseios incompletos não selecionados é bloqueada com mensagem clara para o operador.
- [ ] Ao fechar o turno, é criado o registro `TransferenciaManuseioBladder` indicando turma de origem, turma de destino e quantidades.
- [ ] No quadro do próximo turno (`/bladder/operador/`), a seção "MANUSEIOS RECEBIDOS DO TURNO ANTERIOR" exibe os registros transferidos com ação direta para "RETOMAR MANUSEIO".
- [ ] Ao retomar o manuseio, os dados anteriores e amostras aparecem pré-carregados, permitindo finalizar o saldo restante até atingir `CONCLUIDO`.
- [ ] Nenhuma OP adicional é criada e nenhuma contagem de extrusão é duplicada no sistema.

### Entrega B — Estação de Retirada Noturna com Leitor USB:
- [ ] A conta `noturno_bladder` é criada/provisionada como usuário Django autêntico sem privilégios de staff ou superusuário.
- [ ] O botão "INICIAR PERÍODO NOTURNO" em `/bladder/operador/` abre modal de confirmação e, ao confirmar, autentica o usuário noturno, fecha a sessão anterior com auditoria em `SessaoNoturnaBladder` e redireciona para `/bladder/noturno/`.
- [ ] O middleware não desconecta a sessão noturna por inatividade de 5 minutos, mas encerra a sessão caso atinja o teto de 16 horas.
- [ ] Qualquer tentativa do usuário noturno de acessar URLs fora de `/bladder/noturno/` é bloqueada no backend com redirecionamento para a tela noturna.
- [ ] A tela `/bladder/noturno/` apresenta exclusivamente 3 campos operacionais: Modelo, Lote e Volume.
- [ ] O leitor USB com disparo de `Enter` no campo Lote move o foco para o campo Volume sem submeter o formulário antes da hora.
- [ ] Zeros à esquerda digitados ou lidos no Lote são preservados integralmente (ex: `"003810"`).
- [ ] Tentativa de retirar quantidade superior ao saldo atual do modelo é bloqueada com erro amigável no frontend e no backend.
- [ ] O clique em "CONFIRMAR SAÍDA DO ESTOQUE" possui proteção contra duplo clique, cria a movimentação de saída com idempotência e enfileira a linha correspondente na DR-201.
- [ ] A tabela da sessão exibe as retiradas realizadas em tempo real com hora, modelo, lote e volume.
- [ ] O botão "INICIAR TURNO DIURNO" abre modal solicitando usuário e senha diurnos. Credenciais válidas encerram a sessão noturna, logam o operador diurno e o levam à tela de boas-vindas. Credenciais inválidas mantêm o terminal seguro na tela noturna.

### Entrega C — Tela de Boas-Vindas Contextual:
- [ ] A rota `/bladder/bem-vindo/` exibe saudação contextual correta conforme o horário (Bom Dia / Boa Tarde / Boa Noite) e o nome do usuário.
- [ ] Exibe cartões informativos com dados reais do dia: OPs programadas, metas, manuseios transferidos, alertas de passagem de turno e situação do estoque.
- [ ] O botão "IR PARA O TURNO" direciona para `/bladder/operador/`. Se for líder, exibe também botão para `/bladder/` (dashboard).
- [ ] O fluxo pós-login (`home_redirect` e `portal_select`) direciona o operador para a tela de boas-vindas no primeiro acesso da sessão (`bladder_welcome_seen = False`).
- [ ] Após visualizar a tela de boas-vindas uma vez, requisições normais e F5 mantêm o operador no seu ambiente de trabalho sem reapresentar a tela de boas-vindas em loop.
- [ ] Nenhum outro módulo do sistema (`maintenance`, `matrizaria`, `production`) é impactado no roteamento.

### Entrega D — Correções de Legibilidade no Fechamento do Turno (WCAG AA):
- [ ] Eliminados todos os containers `bg-black bg-opacity-*` de `fechamento_turno.html`.
- [ ] Textos de produtos, OPs, metas e observações utilizam paleta de tema claro (`#0F172A`, `#1E293B`, `#334155`), com contraste superior a **4.5:1** contra os fundos de cartão brancos (`#FFFFFF`).
- [ ] O bloco de déficit de produção utiliza fundo vermelho suave (`#FEF2F2`) com textos contrastados, garantindo legibilidade perfeita sob iluminação fabril.
- [ ] Os botões de seleção de categorias utilizam contraste de interface superior a **3:1** tanto no estado inativo quanto no selecionado.
- [ ] A tabela de fechamento auditado em somente leitura é renderizada em tema claro limpo, sem conflito de cores.
- [ ] Testes de responsividade aprovados em resoluções de **375px**, **768px** e **1366px**, sem transbordo de tela ou quebra de layout.

---

## ⚠️ 10. RISCOS MAPEADOS E ESTRATÉGIAS DE MITIGAÇÃO

| Risco Mapeado | Impacto | Estratégia de Mitigação Obrigatória |
|---|---|---|
| Disparo acidental do leitor USB submeter o formulário sem volume | Alto (saída com volume incorreto ou zero) | Interceptar tecla Enter (`keydown`) no campo Lote via JS, prevenindo o submit e focando no campo Volume; validação estrita no backend de `volume > 0`. |
| Concorrência no estoque físico durante retirada noturna rápida | Alto (saldo inconsistente ou negativo) | Uso de `select_for_update()` no modelo `ProdutoBladder` dentro de `transaction.atomic(using='default')` e verificação estrita `saldo_anterior - qtd >= 0`. |
| Duplo clique do operador no botão de retirada ou fechamento | Médio (duplicação de registros) | Token de idempotência UUID no formulário e desabilitação do botão no primeiro clique com feedback visual (`spinner-border`). |
| Sessão noturna aberta esquecida por dias no chão de fábrica | Alto (risco de segurança) | Teto absoluto de expiração no middleware configurado em 16 horas (`NIGHT_SHIFT_MAX_SECONDS = 16 * 3600`). |
| Loop de redirecionamento entre login, boas-vindas e turno | Médio (travamento da navegação do operador) | Uso de flag atômica na sessão `request.session['bladder_welcome_seen'] = True` logo na renderização de `boas_vindas_view`. |
| Incompatibilidade de migrações entre SQLite e MySQL | Alto (falha no deploy de produção) | Criar campos com valores default ou `null=True, blank=True`; não utilizar tipos de dados proprietários ou SQL puro. |

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO EM FASES (ORDEM PARA O BACKEND)

```
[Fase 1: Modelos e Migrações]
  ├── Alteração em ApontamentoTurnoBladder (quantidade_manuseada, status_manuseio)
  ├── Criação de TransferenciaManuseioBladder
  ├── Criação de SessaoNoturnaBladder
  └── Execução segura de makemigrations e migrate (default)

[Fase 2: Serviços e Lógica de Negócio (services.py, producao.py)]
  ├── Lógica de Manuseio Parcial e Cálculo de Amostras
  ├── Lógica de Transferência Seletiva no Fechamento
  ├── Serviços de Ativação, Retirada e Encerramento Noturno
  └── Provisionamento idempotente do usuário 'noturno_bladder'

[Fase 3: Middleware e Autenticação (middleware.py, views.py)]
  ├── Regras de isenção e teto de 16h para Turno Noturno no middleware
  ├── Bloqueio de rotas não noturnas para a identidade restrita
  └── Integração da tela de boas-vindas em home_redirect e portal_select

[Fase 4: Views, Formulários e Rotas (views.py, urls.py, forms_producao.py)]
  ├── Views de Estação Noturna (/bladder/noturno/*)
  ├── View de Boas-Vindas (/bladder/bem-vindo/)
  └── Atualização de operador_turno e fechamento_turno

[Fase 5: Templates e Correção WCAG AA (HTML & CSS)]
  ├── Refatoração completa de fechamento_turno.html para Tema Claro WCAG AA
  ├── Implementação de noturno_estacao.html (3 campos + leitor USB)
  ├── Implementação de bem_vindo.html (dashboard de recepção)
  └── Atualizações em operador_turno.html e producao_form.html

[Fase 6: Testes Automatizados e Manuais]
  ├── Testes unitários de serviços de manuseio e transferência
  ├── Testes de concorrência e idempotência de estoque
  ├── Testes de permissões e confinamento de rotas da sessão noturna
  └── Validação de contraste WCAG AA com ferramentas de inspeção
```

---

## 🧪 12. ROTEIRO DE TESTES MANUAIS OBRIGATÓRIOS

### Teste 1: Manuseio Parcial e Encaminhamento entre Turnos
1. Acessar com operador diurno da Turma A e registrar uma Extrusão de 100 tarugos na OP do dia.
2. Na lista de manuseios pendentes, clicar em "REGISTRAR MANUSEIO".
3. Preencher 40 tarugos manuseados e as 4 primeiras amostras. Clicar no botão **"SALVAR PARCIAL"**.
4. Verificar se o registro foi salvo com situação `PARCIAL` e se a pendência agora indica 60 tarugos restantes.
5. Ir para `/bladder/operador/fechar-turno/`:
   - Verificar se a extrusão aparece na seção de manuseios incompletos.
   - Tentar submeter sem marcar o checkbox de encaminhamento -> verificar se o sistema bloqueia.
   - Marcar o checkbox de encaminhamento para a Turma B e confirmar o fechamento.
6. Fazer login com o operador da Turma B:
   - No quadro operacional `/bladder/operador/`, constatar a seção "MANUSEIOS RECEBIDOS DO TURNO ANTERIOR".
   - Clicar em "RETOMAR MANUSEIO", preencher os 60 tarugos restantes e as amostras complementares.
   - Clicar em **"CONCLUIR MANUSEIO"** e validar o encerramento completo sem duplicação de OP ou produção.

### Teste 2: Estação Noturna com Leitor USB e Saída de Estoque
1. No quadro do operador diurno, clicar em **"INICIAR PERÍODO NOTURNO"** e confirmar a modal.
2. Verificar se o sistema encerra a sessão diurna e redireciona para `/bladder/noturno/` sob a identidade `noturno_bladder`.
3. Tentar acessar `/bladder/operador/` ou `/management/` -> constatar que o middleware redireciona imediatamente para `/bladder/noturno/`.
4. Testar o leitor USB: posicionar o cursor no campo Lote e disparar leitura de etiqueta com Enter no final -> verificar se o formulário **não** é submetido e o foco muda para o campo Volume.
5. Digitar volume manual maior que o saldo em estoque -> verificar bloqueio imediato.
6. Digitar volume válido (ex: 2 unidades) e clicar em **"CONFIRMAR SAÍDA DO ESTOQUE"**.
7. Verificar se o saldo do produto diminui em 2 un, se a linha aparece na tabela de saídas da sessão e se a movimentação é enfileirada para a DR-201.
8. Clicar em **"INICIAR TURNO DIURNO"**:
   - Inserir credenciais inválidas -> verificar erro na modal sem sair da tela noturna.
   - Inserir credenciais válidas do operador diurno -> verificar que a sessão noturna fecha, a sessão diurna é iniciada e a tela `/bladder/bem-vindo/` é exibida.

### Teste 3: Tela de Boas-Vindas e Navegação Pós-Login
1. Fazer logout e login novamente como operador diurno.
2. Constatar redirecionamento automático para `/bladder/bem-vindo/`.
3. Validar a saudação ("BOM DIA..." / "BOA TARDE..."), escala do dia, cartões de OPs, manuseios recebidos e recados.
4. Clicar em **"IR PARA O TURNO"** -> acessar `/bladder/operador/`.
5. Pressionar F5 ou navegar para outras abas -> constatar que permanece no quadro operacional sem ser jogado novamente para a tela de boas-vindas.

### Teste 4: Contraste WCAG AA no Fechamento de Turno
1. Acessar `/bladder/operador/fechar-turno/` em tema claro.
2. Inspecionar com ferramenta de acessibilidade (Lighthouse / DevTools Contrast Checker):
   - Texto dos produtos e OPs contra o fundo do card: verificar ratio `> 7:1`.
   - Box de justificativa de desvio (vermelho suave com texto escuro): verificar ratio `> 4.5:1`.
   - Botões de seleção de categorias: verificar ratio `> 3:1`.
3. Reduzir a largura da janela para 375px e 768px: verificar legibilidade, ausência de quebras de layout e espaçamento de botões para toque (min 48px).

---

## 📂 13. DIRETRIZES TÉCNICAS E ORIENTAÇÕES PARA O SUBAGENTE BACKEND

1. **Ordem de Implementação:** Seguir estritamente o plano de fases da Seção 11.
2. **Migrations:** Gerar migrações defensivas com nomes descritivos (ex: `00XX_evolucao_operacional_turnos_bladder.py`). Testar localmente `python manage.py makemigrations bladder` e `python manage.py migrate`.
3. **Provisionamento Idempotente do Usuário Noturno:** Criar rotina/service que garanta a existência do usuário `noturno_bladder` com senha inativa ou gerenciada por hash seguro (o login noturno é feito via transição de sessão com `auth.login`, dispensando digitação de senha na ativação).
4. **Isolamento de Banco:** Todas as queries devem continuar usando `using('default')` ou padrão ORM. Zero chamadas a `scada`.
5. **Preservação de Código:** Não refatorar ou excluir funções de produção existentes (`registrar_producao`, `corrigir_producao`, `sincronizacao_drs.py`), apenas estendê-las para suportar manuseio parcial e transferências.
6. **Evidências:** Ao concluir, registrar no relatório final os arquivos criados e alterados, detalhando as regras implementadas e confirmando a ausência de regressões.


---

## 📋 14. EVIDÊNCIAS DA HOMOLOGAÇÃO E MATRIZ DE TESTES AUTOMATIZADOS (SUBAGENTE QA)

Data da Homologação: 18/11/2026  
Responsável: **Subagente QA do Painel de Manutenção Industrial**  
Resultado Global: **APROVADO (100% DOS CRITÉRIOS ATENDIDOS, ZERO REGRESSÕES)**  

### 14.1 Verificações Técnicas do Django
- `python manage.py check`: **0 issues identificadas** (OK).
- `python manage.py makemigrations --check --dry-run`: **No changes detected** (OK).
- Migration `0013_evolucao_operacional_turnos_bladder`: íntegra e aplicada.

### 14.2 Matriz de Testes Automatizados — `tests_evolucao_operacional.py` (43 Testes Aprovados)

| Seção | Classe de Teste | Quantidade de Cenários | Status |
|---|---|---|---|
| **Seção 27** | `EvolucaoOperacionalEntregaATestCase` (Manuseio Parcial e Transferência Seletiva) | 12 cenários (Cenários 1 a 12) | **12/12 APROVADOS (100%)** |
| **Seção 28** | `EvolucaoOperacionalEntregaBTestCase` (Modo Noturno e Estação USB) | 21 cenários (Cenários 1 a 21) | **21/21 APROVADOS (100%)** |
| **Seção 29** | `EvolucaoOperacionalEntregaCTestCase` (Boas-Vindas e Roteamento Inteligente) | 8 cenários (Cenários 1 a 8) | **8/8 APROVADOS (100%)** |
| **Entrega D** | `EvolucaoOperacionalEntregaDTestCase` (Contraste WCAG AA e Responsividade) | 2 cenários (Cenários 1 e 2) | **2/2 APROVADOS (100%)** |

### 14.3 Suíte Global de Regressão
- `python manage.py test bladder --noinput`: **368/368 testes aprovados (100% OK, 0 erros, 0 falhas)**.
- `python manage.py test maintenance --noinput`: **74/74 testes aprovados (100% OK, 0 erros, 0 falhas)**.

### 14.4 Evidência Central da Prova de Estoque e DR-201
- **Saldo Inicial:** 20 unidades de BLA240
- **Retirada Noturna:** 5 unidades (Lote: `LOTE-PROVA-20-15`, Volume: 5)
- **Saldo Final:** 15 unidades
- **Ledger:** Exatamente 1 movimentação `SAIDA` gravada com `idempotency_key`
- **DR-201:** Exatamente 1 linha enfileirada assincronamente com chave de idempotência UUID, sem duplicação contra duplo disparo.

### 14.5 Conclusão da Homologação
Todas as 4 entregas normativas estão plenamente integradas, seguras, auditadas e em estrita conformidade com `constitution.md`.
