# PROMPT — FASE 4: CADASTRO DE OS POR FOTO & VALIDAÇÃO ANTI-DUPLICIDADE

## 📌 Contexto & Objetivo
Nesta Fase 4, vamos construir a interface de usuário (UI) e o fluxo completo de cadastro da Ordem de Serviço. O objetivo é permitir que líderes de produção ou operadores escaneiem a folha física com o celular, validem o preenchimento assistido por IA e registrem a OS com upload obrigatório da foto de abertura e prevenção estrita de duplicidade.

---

## 🔒 Regras da Constituição a Seguir
- Interface 100% em Português Brasileiro (pt-br), limpa e amigável para telas de celular no chão de fábrica.
- Validação estrita de unicidade do `numero_os` no Form e no Model.
- Decorators de proteção de rota no backend (Líderes de Produção, Técnicos Líderes e Operadores podem cadastrar OS).
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. Form de Criação (`maintenance/forms.py` -> `OrdemServicoCreateForm`)
- Campos: `numero_os`, `setor`, `maquina`, `solicitante`, `tipo_manutencao`, `criticidade`, `descricao_falha`, `tecnico_designado`, `foto_abertura`.
- **Validação de Unicidade (`clean_numero_os`):**
  ```python
  def clean_numero_os(self):
      numero = self.cleaned_data.get('numero_os', '').strip().upper()
      if not numero:
          raise forms.ValidationError("O número da Ordem de Serviço física é obrigatório.")
      qs = OrdemServico.objects.filter(numero_os__iexact=numero)
      if self.instance.pk:
          qs = qs.exclude(pk=self.instance.pk)
      if qs.exists():
          os_existente = qs.first()
          raise forms.ValidationError(
              f"A OS nº {numero} já está cadastrada (Criada em {os_existente.data_abertura.strftime('%d/%m/%Y')} - Status: {os_existente.get_status_display()})."
          )
      return numero
  ```
- **Validação de Foto Obrigatória:**
  - `foto_abertura` deve ser obrigatória na criação inicial via formulário de abertura.

### 2. View de Criação de OS (`maintenance/views.py` -> `os_create`)
- Rota: `/ordens-servico/nova/` (nome: `os_create`).
- Permissões: Permitido para `Operadores`, `Tecnicos_Lideres` e membros do grupo `Liderança de Produção`.
- Ao salvar:
  - Define `criado_por = request.user`.
  - Define `status = 'PENDENTE'` (ou `EM_ANDAMENTO` se já foi designado e iniciado).
  - Emite mensagem de sucesso `messages.success(request, f"Ordem de Serviço #{os.numero_os} aberta com sucesso!")`.
  - Redireciona para o Quadro de OSs (`/ordens-servico/`) ou tela de gerenciamento.

### 3. Template `maintenance/os_create.html` (Mobile-First)
- **Área de Captura de Foto:**
  - Card visual no topo: Botão grande **"Tirar Foto da OS / Enviar Arquivo"** com `<input type="file" accept="image/*" capture="environment">`.
  - Área de pré-visualização da imagem capturada.
  - Botão com ícone de varinha/IA: **"Escanear com IA (Preenchimento Automático)"**.
- **Comportamento JavaScript (Assíncrono):**
  - Ao clicar em escanear, exibe um modal ou spinner elegante (*"Processando caligrafia com IA..."*).
  - Faz chamada `fetch` para `/api/os/extrair-foto/`.
  - Ao receber a resposta:
    - Preenche automaticamente o campo `#id_numero_os`.
    - Seleciona o `#id_setor` e `#id_maquina`.
    - Preenche `#id_solicitante`, `#id_tipo_manutencao`, `#id_criticidade` e `#id_descricao_falha`.
    - Realça visualmente com animação suave os campos preenchidos pela IA para o operador apenas bater o olho e conferir.
  - Se a IA falhar ou estiver sem internet: exibe um alerta suave informando que o formulário pode ser digitado manualmente sem nenhum bloqueio.
- **Validação Anti-Duplicidade Instantânea no Frontend:**
  - Ao perder o foco (`blur`) do campo `numero_os`, uma checagem rápida avisa imediatamente se aquele número já existe no banco antes mesmo do usuário enviar o formulário.

### 4. Botão de Acesso Rápido nas Barras de Navegação
- Adicionar botão **"+ Nova OS"** no topo de `base.html` e `base_production.html` visível para usuários autorizados.

---

## 🧪 Critérios de Aceite e Validação
1. Abertura do formulário em tela desktop e mobile sem quebras de layout.
2. Upload de foto real com ativação do scanner IA: os campos do formulário são pré-preenchidos.
3. Teste de tentativa de envio com número de OS duplicado: o formulário exibe mensagem clara de erro e impede a gravação.
4. Teste de tentativa de envio sem foto de abertura: o formulário exige o anexo.
5. OS criada com sucesso aparece no banco com a foto armazenada em `media/ordens_servico/abertura/`.
6. Atualização registrada em `Instrucoes.txt`.
