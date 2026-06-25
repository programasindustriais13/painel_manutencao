# 🧠 SPEC — FASE 2: INTEGRAÇÃO COM WHATSAPP (BAILEYS) E MICROSERVIÇO NODE.JS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/relatorio-turno/`
- **Contexto(s):** Envio automatizado do relatório de passagem de turno.
- **Perfil(s) afetados:** Técnico Líder e Operador/Administrador.

---

## ❗ 2. PROBLEMA ATUAL

- A Fase 1 estruturou a tela de prévia do relatório e o salvamento do número no banco de dados. No entanto, o botão "Enviar" atualmente apenas simula a ação. 
- O backend principal (Django) roda em Python, mas a biblioteca de WhatsApp escolhida (Baileys) roda em Node.js. Precisamos de uma ponte de comunicação entre os dois e de um manual claro para que a gestão possa configurar o Node.js no ambiente local e futuramente no Windows Server.

---

## 🎯 3. OBJETIVO

- **Microserviço (Mensageiro):** Criar uma pasta isolada no projeto contendo um script Node.js mínimo (usando Express e Baileys) que gere o QR Code no terminal e abra uma rota POST para receber mensagens.
- **Backend (Django):** Alterar a view do relatório para, ao receber o POST do formulário, disparar uma requisição HTTP real para o microserviço Node.js contendo o telefone do técnico e o texto editado.
- **Documentação:** Criar um arquivo Markdown com o passo a passo de configuração e execução do Node.js.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Novos arquivos:
- [SPEC_INTEGRACAO_WHATSAPP_BAILEYS.md](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/regras_programacao/SPEC_INTEGRACAO_WHATSAPP_BAILEYS.md) (Esta especificação)
- [package.json](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/package.json) (Definição de dependências do Node.js)
- [server.js](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/server.js) (Lógica do Baileys e servidor Express)
- [SETUP_WHATSAPP.md](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/SETUP_WHATSAPP.md) (Manual de instalação e uso para o usuário)

### Arquivos existentes a serem modificados:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Alterar submissão POST na view `relatorio_turno` para enviar dados ao serviço do WhatsApp)
- [requirements.txt](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/requirements.txt) (Adicionar dependência `requests`)
- [Instrucoes.txt](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/Instrucoes.txt) (Atualizar a documentação histórica do projeto)

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar integrações com APIs pagas. O uso deve ser estrito à biblioteca open-source `@whiskeysockets/baileys`.
- NÃO instalar bibliotecas de Node.js globalmente. O `package.json` deve conter tudo.
- NÃO alterar a lógica de geração de texto da Fase 1, apenas a ação de envio.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Manter a integridade do ambiente virtual Python existente.
- ✅ O Node.js deve ser um serviço totalmente isolado, que não interfira na inicialização do `runserver` do Django.
- ✅ O Django DEVE tratar possíveis falhas de conexão com o Node.js (ex: usar bloco try/except em requisições) para não estourar erro 500 na tela do usuário caso o servidor do WhatsApp esteja desligado.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **O Microserviço (server.js):**
   - Rodar na porta `3000`.
   - Ao iniciar, deve inicializar o Baileys e imprimir o QR Code no terminal (`qrcode-terminal`) para autenticação do celular remetente.
   - Salvar as credenciais de sessão localmente no diretório `auth_info_baileys` para não exigir escaneamento toda vez que for reiniciado.
   - Deve expor a rota `POST /send`, aguardando um JSON com `numero` e `mensagem`.
   - Deve formatar o número corretamente para o padrão do WhatsApp (adicionando o DDI 55 do Brasil se faltar e o sufixo `@s.whatsapp.net`).
2. **O Cliente (views.py):**
   - Na view do relatório, após o usuário clicar em "Enviar", capturar o texto do formulário e o campo `whatsapp` do cadastro do técnico logado.
   - Enviar uma requisição `POST` via `requests` para `http://localhost:3000/send`.
   - Se o técnico não possuir WhatsApp cadastrado, exibir aviso na tela: *"Relatório salvo, mas o técnico não possui número de WhatsApp cadastrado."*
   - Se a requisição retornar sucesso (200), exibir um Django Message de sucesso. Se retornar erro ou timeout, exibir um aviso amigável: *"Relatório salvo, mas o servidor de WhatsApp está offline."*
3. **O Manual (SETUP_WHATSAPP.md):**
   - Documento claro focado no usuário não-Node.js.
   - Deve conter: Como instalar o Node.js; Como rodar `npm install` na pasta; Como rodar `node server.js`; Como ler o QR Code; e avisos sobre como manter isso rodando no Windows Server futuramente (ex: uso do PM2 ou janela aberta).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Arquivo `SETUP_WHATSAPP.md` criado e detalhado.
- [ ] Pasta `whatsapp_service` contendo `server.js` funcional.
- [ ] Ao rodar o Node, o terminal exibe o QR Code.
- [ ] Ao submeter o formulário no Django, a mensagem chega no celular de destino configurado no perfil.
- [ ] Se o Node estiver desligado, o Django trata o erro elegantemente na tela.

---

## ⚠️ 9. RISCOS

- **Formatação de Número:** O WhatsApp exige o número em um formato muito específico (`55dddnumero@s.whatsapp.net`). O script Node.js deve higienizar o número que vem do Django (remover parênteses, traços, espaços e garantir que tenha o `55` na frente).
- **Sessão do Baileys:** Garantir que o script salve os dados de sessão (auth_info) localmente em uma pasta para não pedir o QR Code toda vez que reiniciar.
- **Instabilidade da Conexão:** A conexão com o WhatsApp Web pode ser desconectada por inatividade. O script deve tentar reconectar automaticamente.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Criar o diretório e arquivos base do Node.js (`package.json`, `server.js`).
2. Escrever a lógica do Baileys para salvar sessão, gerar QR no terminal e aceitar chamadas via Express.
3. Criar o arquivo `SETUP_WHATSAPP.md`.
4. Editar a `views.py` da aplicação Django para fazer o POST HTTP para o endpoint local do Node.js, envelopando em um bloco de tratamento de exceção (`try/except requests.exceptions.RequestException`).
5. Validar o fluxo completo.

---

## 🧪 11. TESTES MANUAIS

1. Iniciar o microserviço Node na pasta `whatsapp_service`.
2. Escanear o QR Code exibido no terminal utilizando o WhatsApp do celular.
3. Acessar a tela de Passagem de Turno `/relatorio-turno/` como Técnico com número cadastrado.
4. Enviar o relatório e checar se a mensagem é enviada ao destinatário correto.
5. Desligar o microserviço Node, tentar enviar novamente e verificar se o sistema exibe o aviso amigável sem crashar.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados/criados (destacando o `SETUP_WHATSAPP.md`)
- Alterações feitas
- Justificativa
