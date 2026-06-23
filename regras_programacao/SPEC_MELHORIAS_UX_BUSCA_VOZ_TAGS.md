# 🧠 SPEC — MELHORIAS DE UX: BUSCA EM TEMPO REAL E DIGITAÇÃO POR VOZ/TAGS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/management/`
- **Contexto(s):** Controle de Técnicos (Painel de Gerenciamento via Smartphone/Mobile)
- **Perfil(s) afetados:** Técnico Líder, Operador e Técnico Comum.

---

## ❗ 2. PROBLEMA ATUAL

- **Localização de Técnicos:** O Técnico Líder perde muito tempo rolando a tela do smartphone para localizar um técnico específico no painel `/management/`, pois a lista é extensa.
- **Dificuldade de Digitação:** Os técnicos operam no chão de fábrica e frequentemente estão com as mãos sujas de graxa, o que torna a digitação de textos longos nos campos de "Observação" (ao iniciar, pausar ou concluir serviços) lenta e frustrante.

---

## 🎯 3. OBJETIVO

- **Busca em Tempo Real (Live Search):** Implementar um campo de pesquisa no topo da tela `/management/` que filtre instantaneamente os cards dos técnicos conforme o usuário digita (via JavaScript), mantendo a ordem alfabética original.
- **Facilitador de Texto (Voz e Tags Rápidas):** Adicionar nos modais de ação (Pausa e Conclusão) um botão de Microfone (usando a Web Speech API nativa do navegador para transcrever voz para texto) e botões de "Textos Rápidos" (ex: "Falta de Peça", "Aguardando Produção", "Limpeza") que injetem o texto diretamente no campo de observação com um clique.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance/templates/maintenance/technician_management.html` (Foco 100% no HTML e scripts JavaScript).

### Possíveis módulos:
- Apenas frontend da aplicação (CSS/JS local no template).

---

## 🚫 5. FORA DE ESCOPO

- Não alterar a lógica de ordenação do backend (NÃO implementar auto-sort; manter a ordem alfabética atual gerada pela view).
- Não utilizar APIs de voz pagas (Google Cloud, AWS). Utilizar estritamente a API nativa do navegador (Web Speech API / `webkitSpeechRecognition`).
- Não alterar banco de dados (os Textos Rápidos podem ser adicionados hardcoded no HTML/JS para evitar complexidade no banco).
- Não criar novas views ou rotas.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ❌ Não criar múltiplos ambientes (.venv2, etc)
- ❌ Não duplicar projeto ou apps
- ❌ Não alterar estrutura de banco sem justificativa
- ✅ Reutilizar código existente
- ✅ Foco em JavaScript puro/vanilla ou jQuery (o que já estiver no projeto).

---

## ⚙️ 7. REGRAS DE NEGÓCIO

- **Live Search:** A busca deve ignorar maiúsculas/minúsculas (case-insensitive) e acentos, ocultando (via `display: none`) os cards (ou linhas) dos técnicos que não corresponderem à pesquisa.
- **Textos Rápidos:** Ao clicar em um texto rápido, o valor deve ser *acrescentado* (concatenado) ao texto que já estiver na caixa de observação, com um espaço antes, para não apagar o que o técnico já digitou.
- **Comando de Voz:** O botão de microfone deve solicitar permissão do navegador apenas na primeira vez. Enquanto escuta, deve ter um feedback visual (ex: botão piscando em vermelho ou ícone mudando).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [x] Campo de busca no topo filtra os técnicos imediatamente sem recarregar a página.
- [x] Ordem alfabética original dos cards não é alterada pela busca.
- [x] Modais de pausa e conclusão possuem os botões de voz e tags rápidas visíveis e responsivos para celular.
- [x] Microfone captura a voz e transcreve para a caixa de texto.
- [x] Tags rápidas injetam o texto na caixa sem apagar o conteúdo existente.

---

## ⚠️ 9. RISCOS

- **Web Speech API:** Alguns navegadores mobile mais antigos ou sem permissão de microfone podem bloquear a função. Adicionar um try/catch no JavaScript para que, se a API não for suportada, o botão do microfone apenas não apareça ou exiba um alerta amigável, sem quebrar os modais.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Inspecionar `technician_management.html` e identificar a estrutura de container dos cards de técnicos.
2. Adicionar o input de `<input type="text" id="liveSearchTech" placeholder="Buscar técnico...">` no topo.
3. Criar a função JavaScript `liveSearch()` vinculada ao evento `keyup` ou `input` do campo de busca.
4. Identificar os modais de Iniciar, Pausar e Concluir e seus respectivos `textarea`.
5. Adicionar a UI (HTML/CSS) dos botões de tags e microfone próximos aos campos.
6. Criar as funções JavaScript `insertQuickTag()` e `startSpeechRecognition()`.
7. Testar fluxo completo.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/management/`.
2. Digitar o nome de um técnico na barra de busca (com letras minúsculas e maiúsculas) e verificar se apenas ele aparece.
3. Limpar a busca e verificar se todos voltam a aparecer.
4. Abrir o modal de "Pausar" de qualquer serviço ativo.
5. Clicar em uma Tag Rápida (ex: "Falta de Peça") e ver se preenche o textarea.
6. Clicar no botão de microfone, falar uma frase e ver se o texto é adicionado no textarea.
7. Concluir o formulário normalmente.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
