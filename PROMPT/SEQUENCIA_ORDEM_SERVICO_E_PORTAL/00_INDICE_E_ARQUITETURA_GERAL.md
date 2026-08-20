# 🗺️ ÍNDICE E ARQUITETURA GERAL — IMPLEMENTAÇÃO EM SEQUÊNCIA

Este diretório contém a sequência de prompts modulares e incrementais para a implementação das novas funcionalidades do sistema:
1. **Portal Seletor Pós-Login & Correção de Roteamento de Módulos.**
2. **Sistema Completo de Ordens de Serviço (OS) com IA/OCR de Caligrafia, Múltiplos Técnicos, Anti-duplicidade e Fotos Obrigatórias de Abertura e Assinatura de Fechamento.**

---

## 📋 Regra de Ouro para Execução
Cada fase depende estritamente da conclusão bem-sucedida da fase anterior. 
Ao iniciar uma etapa, execute apenas o prompt correspondente e valide todos os critérios de aceite antes de avançar.

Durante a execução de qualquer fase, devem ser rigorosamente respeitadas as diretrizes da **`constitution.md`**:
- Apenas **1 ambiente virtual (`.venv`)** e **1 base de código ativa**.
- Backend Django MVT seguro com validação de permissões no backend (nunca confiar apenas no frontend).
- Migrações aditivas e 100% compatíveis com **SQLite** (desenvolvimento) e **MySQL** (produção).
- Manter o registro atualizado no arquivo **`Instrucoes.txt`** ao concluir cada fase.

---

## 🗂️ Estrutura das Fases

| Arquivo | Fase | Descrição do Escopo |
| :--- | :--- | :--- |
| [`01_FASE1_PORTAL_LOGIN_E_ROTEAMENTO.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/01_FASE1_PORTAL_LOGIN_E_ROTEAMENTO.md) | **Fase 1** | Portal Seletor de Módulos (Hub Pós-Login), regras de bypass automático por perfil e correção do link do logo na Produção. |
| [`02_FASE2_MODELAGEM_ORDEM_SERVICO_E_BANCO.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/02_FASE2_MODELAGEM_ORDEM_SERVICO_E_BANCO.md) | **Fase 2** | Modelagem relacional da `OrdemServico` (vínculo 1:N com `Allocation`, número único, fotos, status, campos de auditoria e migrations aditivas). |
| [`03_FASE3_SERVICO_OCR_IA_GEMINI_VISION.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/03_FASE3_SERVICO_OCR_IA_GEMINI_VISION.md) | **Fase 3** | Serviço de Visão Multimodal com IA (Gemini Vision) para leitura e normalização de caligrafia difícil e erros de português em formulários físicos. |
| [`04_FASE4_CADASTRO_OS_POR_FOTO_E_ANTIDUPLICIDADE.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/04_FASE4_CADASTRO_OS_POR_FOTO_E_ANTIDUPLICIDADE.md) | **Fase 4** | Tela/Modal de Abertura de OS por Foto / Scanner com preenchimento assistido por IA, validação anti-duplicidade e upload da foto de abertura. |
| [`05_FASE5_QUADRO_OS_ATRIBUICAO_E_MULTI_TECNICOS.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/05_FASE5_QUADRO_OS_ATRIBUICAO_E_MULTI_TECNICOS.md) | **Fase 5** | Quadro de OSs Pendentes e Em Andamento, atribuição por operador, início de atendimento e suporte a múltiplos técnicos na mesma OS. |
| [`06_FASE6_VINCULO_EMERGENCIAL_E_FINALIZACAO_COM_FOTO.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/06_FASE6_VINCULO_EMERGENCIAL_E_FINALIZACAO_COM_FOTO.md) | **Fase 6** | Vínculo retroativo de OS a atendimentos emergenciais iniciados sem OS e fluxo de finalização com foto obrigatória da OS assinada pelo Líder. |
| [`07_FASE7_TESTES_QA_CONSTITUTION_E_DOCUMENTACAO.md`](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/PROMPT/SEQUENCIA_ORDEM_SERVICO_E_PORTAL/07_FASE7_TESTES_QA_CONSTITUTION_E_DOCUMENTACAO.md) | **Fase 7** | Bateria de testes de ponta a ponta (QA), auditoria de concorrência e segurança, e consolidação das alterações no `Instrucoes.txt`. |

---

## 🚀 Como Iniciar
Abra o arquivo da **Fase 1** e passe as instruções para o agente iniciar a primeira etapa.
