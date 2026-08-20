# PROMPT — FASE 3: SERVIÇO DE IA / OCR MULTIMODAL (GEMINI VISION)

## 📌 Contexto & Objetivo
No ambiente industrial, as ordens de serviço físicas são preenchidas com caneta por diferentes operadores e líderes, resultando em caligrafias difíceis ("letra de médico"), rasuras e erros de português.

Nesta Fase 3, vamos implementar a camada de serviço backend em Python que utiliza Visão Multimodal com IA (Google Gemini Vision API) para ler a foto da OS física, interpretar a caligrafia, corrigir o texto e devolver um JSON estruturado e normalizado para preenchimento automático.

---

## 🔒 Regras da Constituição a Seguir
- Seguir a arquitetura: Lógica pesada e integrações externas ficam na camada **Services / Utils** (`maintenance/services/`), nunca direto nas views ou templates.
- Chave de API lida estritamente de variável de ambiente (`.env`), nunca hardcoded.
- **Resiliência Máxima:** O sistema NUNCA deve travar se a API estiver fora do ar, sem internet ou sem chave configurada. O serviço deve retornar status de erro amigável e permitir o preenchimento manual imediato.
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. Dependência e Configuração de Ambiente
- Verificar se `google-genai` ou `requests` está disponível na `.venv`.
- Adicionar no arquivo `.env.example` e `.env`:
  ```env
  GEMINI_API_KEY=sua_chave_aqui
  ```

### 2. Criação do Módulo `maintenance/services/os_ocr_service.py`
Implementar a classe/função `extrair_dados_os_por_foto(image_file_or_bytes)`:

```python
import os
import json
import logging
from django.conf import settings
from maintenance.models import Machine, Sector

logger = logging.getLogger(__name__)

PROMPT_ESPECIALISTA_OS = """
Você é um especialista em ler fichas industriais impressas de Ordem de Serviço (OS) de manutenção, preenchidas manualmente à caneta com caligrafia cursiva difícil e eventuais erros de português.

Analise a imagem da Ordem de Serviço anexada e extraia as informações com a máxima precisão possível.
Mesmo que a caligrafia esteja difícil ou com erros de ortografia, use o contexto de manutenção industrial para interpretar corretamente.

Retorne EXCLUSIVAMENTE um objeto JSON válido (sem blocos markdown adicionais em volta, apenas o JSON puro) com a seguinte estrutura:

{
  "numero_os": "Número ou código da OS encontrado na folha (apenas números ou código alfanumérico)",
  "solicitante": "Nome legível do solicitante ou líder de produção",
  "setor_texto": "Nome do setor identificado (ex: Vulcanização, Mistura, Prensas, etc.)",
  "maquina_texto": "Nome ou identificação da máquina/equipamento (ex: Prensa 03, Injetora 02, etc.)",
  "tipo_manutencao": "CORRETIVA ou PREVENTIVA ou MELHORIA ou OUTRO",
  "criticidade": "BAIXA ou MEDIA ou ALTA",
  "descricao_falha": "Texto corrigido e pontuado descrevendo o problema, defeito ou solicitação relatada",
  "confianca_leitura": "ALTA ou MEDIA ou BAIXA",
  "observacoes_adicionais": "Qualquer outra informação relevante lida na folha"
}
"""
```

### 3. Match Inteligente com o Banco de Dados
No mesmo serviço, implementar a função `casar_maquina_e_setor(maquina_texto, setor_texto)`:
- Realizar busca no banco de dados local `Machine.objects.all()` e `Sector.objects.all()`.
- Usar comparação insensível a maiúsculas/minúsculas (`__icontains` ou busca normalizada sem acentos).
- Se encontrar a máquina exata ou similar (ex: "Prensa 03" -> `Machine(nome="Prensa 03")`), retornar o objeto `machine_id` e o respectivo `sector_id` para já selecionar no formulário HTML.

### 4. Tratamento de Exceções e Fallbacks
- Se a chave `GEMINI_API_KEY` não estiver definida: retornar `{"sucesso": False, "motivo": "CHAVE_NAO_CONFIGURADA", "mensagem": "Chave Gemini não configurada. Preencha os campos manualmente."}`.
- Se houver falha de rede/timeout: capturar a exceção e retornar `{"sucesso": False, "motivo": "FALHA_CONEXAO", "mensagem": "Não foi possível conectar ao serviço de IA. Preencha os campos manualmente."}`.
- Se a leitura for bem-sucedida: retornar `{"sucesso": True, "dados": dados_json, "maquina_sugerida_id": machine_id, "setor_sugerido_id": sector_id}`.

### 5. Endpoint de API Interno para o Frontend (`/api/os/extrair-foto/`)
- Rota protegida por `@login_required`.
- Recebe `POST` multipart/form-data com o arquivo de imagem `foto_os`.
- Chama `extrair_dados_os_por_foto(foto_os)`.
- Retorna `JsonResponse` com o resultado em menos de 3 segundos.

---

## 🧪 Critérios de Aceite e Validação
1. Endpoint `/api/os/extrair-foto/` responde com status 400 se nenhuma imagem for enviada.
2. Com imagem de teste simulando OS manuscrita, o serviço extrai e normaliza os dados no formato JSON especificado.
3. Teste de resiliência: com chave ausente ou inválida, a API não gera erro 500; responde amigavelmente indicando que o operador pode digitar manualmente.
4. O casamento de nomes de máquina (ex: texto "prensa 2" -> `Machine ID` correspondente) funciona corretamente.
5. Atualização registrada em `Instrucoes.txt`.
