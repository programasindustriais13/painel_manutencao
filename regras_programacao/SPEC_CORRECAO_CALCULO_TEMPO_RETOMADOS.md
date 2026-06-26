# 🧠 SPEC — CORREÇÃO DO CÁLCULO DE TEMPO DECORRIDO EM SERVIÇOS RETOMADOS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/management/` (Painel de Gestão) e `/tv/` (Dashboard de TV).
- **Contexto(s):** Controle de Técnicos / Cards de Atendimento.
- **Perfil(s) afetados:** Todos (Técnico, Técnico Líder, Operador/Líder, Visualizador/TV).

---

## ❗ 2. PROBLEMA ATUAL

- Quando um serviço é pausado, o tempo registrado na tela fica correto (congelado no tempo trabalhado até ali, ex: 42m).
- Porém, ao clicar em "Retomar", o card do "SERVIÇO ATIVO" passa a exibir o tempo total bruto desde a criação da alocação (ex: 20h 20m), ignorando o tempo em que o serviço esteve pausado. 
- O cálculo está fazendo apenas `(Agora - Data Início)`, sem descontar o histórico de pausas, o que gera uma falsa impressão de lentidão no atendimento.

---

## 🎯 3. OBJETIVO

- Corrigir a lógica de cálculo do "Tempo Decorrido" para serviços com status `EM_ATENDIMENTO` que possuem histórico de pausas.
- O tempo exibido deve ser o **Tempo Líquido** (Tempo Decorrido Bruto menos a soma de todas as durações de pausas daquela alocação).
- O recarregamento e exibição contínua na TV e no gerenciamento de técnicos devem manter o tempo líquido correto.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py) (Adicionar propriedade `tempo_decorrido_liquido` e atualizar `tempo_decorrido_str` no modelo `Allocation`).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar a lógica de cálculo do Dashboard (MTTR).
- NÃO alterar a estrutura do banco de dados (sem migrações adicionais).
- NÃO modificar o layout visual dos cards.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Reutilizar código existente.
- ✅ Utilizar propriedades (`@property`) no Django para encapsular a regra de negócio do cálculo de tempo, mantendo o template limpo.
- ❌ Não duplicar lógica existente.
- ✅ Usar ORM do Django.
- ❌ Não usar SQL direto.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Cálculo Backend:** O modelo `Allocation` deve possuir uma propriedade `tempo_decorrido_liquido` que retorna o tempo líquido formatado.
   - *Fórmula:* `Duração Total = (Agora se não tiver data_fim, senão data_fim) - data_inicio`.
   - *Pausas:* Somar `(data_retorno - data_pausa)` de todos os registros em `HistoricoPausa` dessa alocação.
     - Se uma pausa estiver em aberto (sem `data_retorno`), a duração da pausa ativa é calculada usando a data final da alocação ou `Agora` se ainda estiver aberta.
     - Fallback de compatibilidade: se não houver histórico mas a propriedade legada `self.data_pausa` estiver definida, utilizar a mesma regra de pausa ativa.
   - *Resultado:* `Duração Total - Somatório de Pausas`.
2. **Propriedade existente:** A propriedade `tempo_decorrido_str` deve chamar `tempo_decorrido_liquido` para atualizar automaticamente a renderização em todas as telas sem duplicação de lógica.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Ao retomar um serviço que estava pausado com 42m, o card do serviço ativo exibe os mesmos 42m e continua contando a partir dali (ex: 43m, 44m) no próximo carregamento.
- [ ] O recarregamento da página mantém o tempo líquido correto.
- [ ] Serviços recém-iniciados (sem pausas) continuam com a contagem normal do zero.
- [ ] Os testes unitários existentes em `tests.py` continuam passando sem regressões.

---

## ⚠️ 9. RISCOS

- **Fuso Horário (Timezone):** Misturar `datetime.now()` (naive) com `timezone.now()` (aware) na hora de calcular a diferença pode quebrar a aplicação. Use sempre `from django.utils import timezone`.
- **Compatibilidade Retroativa:** Alocações que não possuem histórico na tabela `HistoricoPausa` (por exemplo, de testes ou dados antigos) devem continuar funcionando corretamente através do fallback para `data_pausa`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Analisar o modelo `Allocation` em `models.py`.
2. Criar a propriedade `tempo_decorrido_liquido` no modelo `Allocation` implementando a lógica de somatório de pausas e compatibilidade retroativa.
3. Atualizar a propriedade `tempo_decorrido_str` para retornar `self.tempo_decorrido_liquido`.
4. Executar os testes unitários com `manage.py test` para verificar se tudo continua verde.
5. Criar um novo caso de teste em `tests.py` validando o cálculo de tempo líquido com múltiplas pausas finalizadas e em andamento.

---

## 🧪 11. TESTES MANUAIS

1. Acessar o sistema, iniciar um novo serviço para um técnico.
2. Aguardar 1 minuto e verificar se o tempo decorrido no card exibe "1m".
3. Pausar o serviço.
4. Aguardar 1 minuto (o tempo de pausa acumula).
5. Retomar o serviço e recarregar a página: verificar se o tempo volta a contar a partir de "1m" (descontando o tempo pausado).
6. Finalizar o serviço.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar:

### Arquivos lidos:
- `maintenance/models.py`
- `maintenance/tests.py`

### Arquivos alterados:
- `maintenance/models.py`
- `maintenance/tests.py`

### Alterações feitas:
- Inclusão da propriedade `tempo_decorrido_liquido` e refatoração de `tempo_decorrido_str` em `models.py`.
- Inclusão de testes automatizados para cálculo de tempo com pausas acumuladas em `tests.py`.

### Justificativa:
- Garantir a precisão da exibição do tempo líquido de atendimento, descontando todas as pausas registradas, sem quebrar retrocompatibilidade e mantendo a suite de testes verde.
