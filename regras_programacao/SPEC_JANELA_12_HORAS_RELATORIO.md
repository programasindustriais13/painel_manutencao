# 🧠 SPEC — ALTERAÇÃO DO PERÍODO DO RELATÓRIO PARA JANELA DE 12 HORAS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/relatorio-turno/`
- **Contexto(s):** Geração do texto do relatório de passagem de turno.
- **Perfil(s) afetados:** Técnico Líder e Técnico.

---

## ❗ 2. PROBLEMA ATUAL

- A query que busca os serviços do turno para montar o texto do WhatsApp está filtrando estritamente pelo dia calendário (`hoje = timezone.now().date()` via `timezone.localdate()`). 
- Isso causa um erro grave para os técnicos do turno da noite/madrugada: se o turno começa às 22:00 e termina às 06:00, gerar o relatório às 06:00 omitirá todas as atividades feitas antes da meia-noite, quebrando a integridade do relatório.

---

## 🎯 3. OBJETIVO

- Modificar a lógica de filtro de data na view do relatório de turno. Em vez de usar o "dia de hoje" do calendário, o sistema deve utilizar uma janela de tempo relativa (TimeDelta), buscando todas as alocações iniciadas ou atualizadas/concluídas nas **últimas 12 horas**.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance/views.py` (Atualizar o QuerySet na view `relatorio_turno`).
- `maintenance/tests.py` (Adicionar testes unitários para a janela de 12 horas).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar o template HTML.
- NÃO alterar o texto das mensagens.
- NÃO alterar a estrutura do banco de dados.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Utilizar o módulo nativo `datetime.timedelta` e `django.utils.timezone`.
- ✅ Reutilizar código existente.
- ✅ Usar apenas o ORM do Django.
- ❌ Não usar SQL direto.
- ❌ Não duplicar lógica existente.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Janela de 12 Horas:** Na view `relatorio_turno`, remover a busca por data de hoje calendarizada (`hoje = timezone.localdate()`).
2. Criar uma variável que define o limite inferior do tempo: `limite_tempo = timezone.now() - timedelta(hours=12)`.
3. Importar `timedelta` de `datetime` na view, se ainda não estiver presente.
4. Atualizar o QuerySet de busca de alocações:
   ```python
   allocations = Allocation.objects.filter(
       tecnico=tecnico
   ).filter(
       Q(data_inicio__gte=limite_tempo) | Q(data_fim__gte=limite_tempo)
   ).select_related('maquina')
   ```

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] A view compila com sucesso usando a nova query de `timedelta`.
- [ ] O relatório gerado retorna serviços que cruzaram a meia-noite (desde que dentro da janela de 12 horas retroativas a partir do momento da geração).
- [ ] Serviços mais antigos que 12 horas são omitidos do relatório.
- [ ] Os testes existentes continuam passando, e novos casos cobrindo a janela de 12 horas e cruzamento de meia-noite/limites são testados com sucesso.

---

## ⚠️ 9. RISCOS

- Quebra dos testes unitários que testavam a data local de hoje (`timezone.localdate()`). Os dados nos testes devem coincidir com o intervalo da janela de 12 horas relativa ao momento atual (`timezone.now()`).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Abrir `maintenance/views.py`.
2. Importar `timedelta` de `datetime` na view.
3. Substituir a lógica de busca da data calendarizada de hoje pela lógica da janela retroativa de 12 horas.
4. Atualizar os filtros do QuerySet para usar `__gte=limite_tempo`.
5. Abrir `maintenance/tests.py` e ajustar/adicionar testes unitários correspondentes.
6. Executar os testes automatizados para validação.
7. Atualizar `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. Criar alocações com horários específicos (uma com início há 14 horas, uma há 8 horas atrás, e outra há 2 horas atrás).
2. Acessar `/relatorio-turno/` e verificar que apenas as alocações com menos de 12 horas de antiguidade são exibidas.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
