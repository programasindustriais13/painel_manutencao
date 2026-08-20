# PROMPT — FASE 6: VÍNCULO EMERGENCIAL & FINALIZAÇÃO COM FOTO DE ASSINATURA

## 📌 Contexto & Objetivo
No ritmo da produção, manutenções emergenciais frequentemente são iniciadas pelo técnico no sistema antes de a liderança preencher a folha de papel. Quando a folha é entregue, é necessário poder regularizar e vincular aquele atendimento em andamento à OS física.

Além disso, para fechar o ciclo de governança e auditoria, ao concluir o serviço, o sistema deve exigir a **Foto Final da OS Física preenchida e assinada pelo Líder**, arquivando ambas as fotos (abertura e fechamento).

Nesta Fase 6, vamos implementar:
1. **Funcionalidade de Vincular Atendimento Emergencial (sem OS) a uma OS Física.**
2. **Modal e Fluxo de Conclusão de Serviço com Foto Obrigatória da OS Assinada.**
3. **Tela de Detalhes / Auditoria da OS com Comparativo de Fotos (Abertura x Fechamento) e Histórico Completo de Técnicos.**

---

## 🔒 Regras da Constituição a Seguir
- Não permitir que uma OS seja marcada como `CONCLUIDA` sem a foto da folha física assinada pelo Líder.
- Suporte seguro a uploads de imagem (`null=True, blank=True` no model com validação obrigatória no Form).
- Interface responsiva com suporte a captura de câmera mobile.
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. Vincular OS Física a um Atendimento em Andamento
- **Onde:** No card do técnico em atendimento na tela `/management/`.
- **Botão:** Adicionar botão com ícone de anexo/documento: **"Vincular OS Física"**.
- **Modal / Fluxo de Vínculo:**
  - O usuário tem duas opções:
    - **Opção A (Selecionar OS Pendente):** Escolhe uma OS pendente da lista que seja da mesma máquina.
    - **Opção B (Escanear / Cadastrar Nova OS):** Tira a foto da folha recebida, o OCR lê o número e dados, cria o registro `OrdemServico` e vincula instantaneamente à alocação ativa.
- **Backend:** Atualiza `allocation.ordem_servico = os` e `os.status = 'EM_ANDAMENTO'`.

### 2. Fluxo de Conclusão com Foto Assinada (`FinishServiceForm` & `finish_allocation`)
- **Atualização do Form de Conclusão (`maintenance/forms.py`):**
  - Adicionar campos:
    - `foto_conclusao`: Campo de imagem com validação obrigatória se o serviço estiver vinculado a uma OS.
    - `lider_assinatura_nome`: Nome do líder de produção que assinou a folha (obrigatório).
    - `observacao_fechamento`: Resumo do trabalho executado e causa raiz.
- **Lógica na View `finish_allocation` / `finish_service`:**
  1. Conclui a alocação individual do técnico (`data_fim = timezone.now()`, status `'CONCLUIDO'`).
  2. Verifica se há outros técnicos ainda com alocações abertas na mesma OS.
     - Se houver outros técnicos ativos: a OS continua `EM_ANDAMENTO`.
     - Se este for o último técnico concluindo a OS:
       - Salva `os.foto_conclusao = foto_conclusao`.
       - Salva `os.lider_assinatura_nome = lider_assinatura_nome`.
       - Salva `os.observacao_fechamento = observacao_fechamento`.
       - Salva `os.data_conclusao = timezone.now()`.
       - Atualiza `os.status = 'CONCLUIDA'`.
  3. Atualiza o status do técnico para `OCIOSO`.

### 3. Tela de Detalhes da OS (`maintenance/views.py` -> `os_detail`)
- **Rota:** `/ordens-servico/<int:pk>/` (nome: `os_detail`).
- **Conteúdo da Tela:**
  - Cabeçalho: Número da OS, Status (Badge), Máquina, Setor, Solicitante, Tipo e Criticidade.
  - **Galeria de Comprovação Visual:**
    - Card Esquerdo: **Foto de Abertura da OS** (com zoom ao clicar).
    - Card Direito: **Foto de Conclusão Assinada** (com zoom ao clicar e identificação do líder que assinou).
  - **Tabela de Auditoria de Mão de Obra:**
    - Lista de todos os técnicos que participaram.
    - Horário de entrada, pausas realizadas, horário de saída e tempo líquido de cada técnico.
    - Tempo total homem-hora e tempo total de intervenção da máquina.
  - Linha do tempo das notas de progresso (`AllocationProgressUpdate`) registradas durante o atendimento.

---

## 🧪 Critérios de Aceite e Validação
1. Iniciar atendimento avulso sem OS -> Clicar em "Vincular OS Física" -> Vincular com sucesso -> Card passa a exibir o número da OS vinculada.
2. Finalizar serviço com OS vinculada:
   - Tentar enviar sem a foto de conclusão assinada -> O formulário barra e solicita o anexo.
   - Tentar enviar sem o nome do líder que assinou -> O formulário barra e solicita o nome.
   - Enviar preenchido -> A alocação e a OS são concluídas com sucesso.
3. Abrir tela de detalhes `/ordens-servico/<id>/`: ambas as fotos (abertura e conclusão assinada) são exibidas nitidamente lado a lado.
4. Tabela de técnicos exibe corretamente todos os técnicos que atuaram na OS com seus respectivos tempos calculados.
5. Atualização registrada em `Instrucoes.txt`.
