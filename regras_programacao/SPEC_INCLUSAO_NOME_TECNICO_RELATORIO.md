# 🧠 SPEC — INCLUSÃO DO NOME DO TÉCNICO NO RELATÓRIO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/relatorio-turno/`
- **Contexto(s):** Geração do texto do relatório de passagem de turno.
- **Perfil(s) afetados:** Técnico Líder e Técnico.

---

## ❗ 2. PROBLEMA ATUAL

- O texto gerado automaticamente para o WhatsApp inicia apenas com "Boa noite\nPassagem de turno", sem identificar qual técnico está enviando o relatório. Quando enviado para grupos, isso pode gerar confusão sobre a autoria das atividades.

---

## 🎯 3. OBJETIVO

- Modificar a lógica de concatenação da string do relatório para incluir o nome do técnico logado logo no cabeçalho da mensagem.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance/views.py` (Na view responsável por montar o texto de `relatorio_turno`).
- `maintenance/tests.py` (Para validar as alterações nos testes unitários).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar o modelo de banco de dados.
- NÃO alterar a lógica de envio do WhatsApp (Node.js).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Reutilizar a variável do técnico logado que já está sendo buscada na view para filtrar os serviços.
- ✅ Manter a compatibilidade com SQLite e MySQL (usando apenas Django ORM).
- ✅ Registrar as modificações no arquivo `Instrucoes.txt`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Alteração da String:** Na view `relatorio_turno`, localizar a variável que monta o cabeçalho.
2. Extrair o nome do técnico logado obtido pela variável `tecnico` (`tecnico.nome`).
3. O novo formato do cabeçalho deverá ser:
   ```text
   Boa noite
   Passagem de turno
   Técnico: [Nome do Técnico]
   ```
   O restante do texto (atividades concluídas e pendências) permanece exatamente igual.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Ao clicar para gerar/visualizar o relatório, a caixa de texto já deve vir preenchida com o nome do técnico logado na terceira linha.
- [ ] O cabeçalho no relatório possui exatamente 3 linhas antes da linha vazia e do corpo do relatório.
- [ ] Todos os testes em `maintenance/tests.py` continuam passando e novos asserts cobrindo a inclusão do nome do técnico foram adicionados.

---

## ⚠️ 9. RISCOS

- Quebra de testes unitários existentes que verificam a string gerada no relatório de turno.
- Tratar cenários onde o técnico possa estar ausente de forma limpa (a view já redireciona se `tecnico` for None).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Abrir `maintenance/views.py`.
2. Localizar a view `relatorio_turno`.
3. Modificar a construção da string de cabeçalho concatenando `Técnico: [tecnico.nome]`.
4. Atualizar o arquivo `maintenance/tests.py` para adaptar e enriquecer a asserção que valida o `texto_precompilado`.
5. Executar os testes automatizados para validar que tudo está funcionando perfeitamente.
6. Atualizar o arquivo `Instrucoes.txt` documentando a alteração.

---

## 🧪 11. TESTES MANUAIS

1. Fazer login com o usuário do técnico vinculado.
2. Acessar `/relatorio-turno/`.
3. Confirmar se a caixa de texto inicial contém o nome do técnico na terceira linha do cabeçalho.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

Ao final do processo, o agente informará:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
