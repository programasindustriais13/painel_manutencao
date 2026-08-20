import os
import json
import base64
import logging
import re
import unicodedata
import requests
from typing import Tuple, Optional, Dict, Any

from django.conf import settings
from maintenance.models import Machine, Sector

logger = logging.getLogger(__name__)

PROMPT_ESPECIALISTA_OS = """
Você é um especialista de alta precisão em leitura e interpretação de fichas industriais impressas de Ordem de Serviço (OS) de manutenção da fábrica PNEUS FREEDOM, preenchidas manualmente com caneta por líderes e mecânicos.

A folha física da Ordem de Serviços possui os seguintes blocos:
1. CABEÇALHO:
   - "Ordem de Serviços Nº": número impresso em destaque (geralmente em vermelho, ex: 10216).
2. ETAPA 1 (Abertura pelo Líder de Produção):
   - "TAG:": código ou identificador do equipamento/máquina (ex: "PREN-01", "102", "M-04").
   - "Descrição do equipamento:": nome por extenso do equipamento (ex: "Prensa Vulcanizadora 10", "Torno CNC").
   - "Motivo:": motivo da solicitação (ex: "Vazamento", "Barulho no redutor", "Quebrou esteira").
   - "Tipo de serviço:": opções [CORRETIVA, PREVENTIVA, MELHORIA, PREDIAL]. Identifique qual está marcada com "X" ou assinalada.
   - "Parou a máquina?": verifique se está marcado SIM ou NÃO.
   - "Descrição do serviço a ser realizado:": instruções do defeito e solicitação.
   - "Inicio da Ocorrência": "Data:" e "Hora:" registradas.
   - "Solicitante / Líder": se houver assinatura ou nome.
3. ETAPA 2 (Execução pelo Técnico / Mecânico):
   - "Causa:(Conferir no verso)": diagnóstico técnico da causa da falha (se houver).
   - "Descrição do serviço realizado:": ações de reparo executadas.
   - "Início do Conserto": "Data:" e "Hora:".
   - "Fim do Conserto": "Data:" e "Hora:".
   - "Peças Utilizadas para o serviço": tabela com Código, Descrição e Qtd de cada item.
   - "Mão de Obra": lista de técnicos com Nome, Data, Tempo, Regime.
   - "Visto Executante": assinatura/nome do executante e data.
4. ETAPA 3 (Finalização pelo Líder):
   - "Fim da Ocorrência": "Data:" e "Hora:" (quando a máquina foi liberada rodando).
   - "Visto Responsável": assinatura/nome do líder e data.

INSTRUÇÕES DE TRANSCRIÇÃO:
- Transcreva o que foi escrito à mão, corrigindo pequenos erros de ortografia da língua portuguesa e pontuação.
- Se a caligrafia for difícil ("letra cursiva de médico"), use o contexto de manutenção mecânica/elétrica industrial de pneus para inferir a palavra correta.
- Se um campo estiver em branco na folha, retorne null ou string vazia.
- Para datas, retorne no formato "AAAA-MM-DD" se possível, ou string legível no formato "DD/MM/AAAA".
- Para horas, retorne no formato "HH:MM".
- Para tipo_manutencao, use: "CORRETIVA", "PREVENTIVA", "MELHORIA", "PREDIAL" ou "OUTRO".
- Para parou_maquina, retorne booleano true ou false.

Retorne EXCLUSIVAMENTE um objeto JSON válido (sem texto explicativo antes ou depois) com a estrutura:
{
  "numero_os": "Número impresso da OS (apenas dígitos/código)",
  "tag": "TAG identificada",
  "descricao_equipamento": "Nome do equipamento",
  "motivo": "Motivo do chamado",
  "tipo_manutencao": "CORRETIVA ou PREVENTIVA ou MELHORIA ou PREDIAL ou OUTRO",
  "parou_maquina": true,
  "descricao_falha": "Texto completo da descrição do serviço a ser realizado",
  "data_inicio_ocorrencia": "AAAA-MM-DD ou DD/MM/AAAA",
  "hora_inicio_ocorrencia": "HH:MM",
  "solicitante": "Nome do solicitante/líder se identificado",
  "causa": "Texto da causa ou null se em branco",
  "descricao_servico_realizado": "Texto do serviço realizado ou null se em branco",
  "data_inicio_conserto": "AAAA-MM-DD ou null",
  "hora_inicio_conserto": "HH:MM ou null",
  "data_fim_conserto": "AAAA-MM-DD ou null",
  "hora_fim_conserto": "HH:MM ou null",
  "data_fim_ocorrencia": "AAAA-MM-DD ou null",
  "hora_fim_ocorrencia": "HH:MM ou null",
  "visto_executante_nome": "Nome do executante ou null",
  "visto_executante_data": "AAAA-MM-DD ou null",
  "visto_responsavel_nome": "Nome do líder ou null",
  "visto_responsavel_data": "AAAA-MM-DD ou null",
  "pecas_utilizadas": [
    {
      "codigo": "Código do material",
      "descricao": "Descrição da peça",
      "quantidade": 1.0
    }
  ],
  "mao_de_obra": [
    {
      "nome": "Nome do técnico",
      "data": "Data",
      "tempo": "Tempo gasto",
      "regime": "Normal / Extra"
    }
  ],
  "confianca_leitura": "ALTA ou MEDIA ou BAIXA",
  "observacoes_adicionais": "Observações sobre a leitura da imagem"
}
"""


def normalizar_texto(texto: str) -> str:
    """Remove acentuação, caracteres especiais e converte para minúsculas."""
    if not texto:
        return ""
    texto = unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8')
    return re.sub(r'[^a-zA-Z0-9\s]', '', texto).strip().lower()


def casar_maquina_e_setor(
    maquina_texto: str = "", 
    tag_texto: str = "", 
    setor_texto: str = ""
) -> Tuple[Optional[Machine], Optional[Sector]]:
    """
    Tenta encontrar a máquina e setor mais compatíveis no banco de dados local.
    """
    machine = None
    sector = None

    # 1. Busca por TAG
    if tag_texto:
        tag_clean = tag_texto.strip()
        m = Machine.objects.filter(nome__iexact=tag_clean).first()
        if not m:
            m = Machine.objects.filter(nome__icontains=tag_clean).first()
        if m:
            machine = m

    # 2. Busca por Descrição / Nome da Máquina
    if not machine and maquina_texto:
        maq_clean = maquina_texto.strip()
        m = Machine.objects.filter(nome__iexact=maq_clean).first()
        if not m:
            m = Machine.objects.filter(nome__icontains=maq_clean).first()
        if not m:
            # Tenta busca com normalização de acentos e termos parciais
            norm_maq = normalizar_texto(maq_clean)
            for m_cand in Machine.objects.select_related('setor').all():
                norm_cand = normalizar_texto(m_cand.nome)
                if norm_maq and (norm_maq in norm_cand or norm_cand in norm_maq):
                    machine = m_cand
                    break
        else:
            machine = m

    if machine and machine.setor:
        sector = machine.setor

    # 3. Se o setor ainda não foi definido e veio texto de setor
    if not sector and setor_texto:
        sec_clean = setor_texto.strip()
        s = Sector.objects.filter(nome__iexact=sec_clean).first()
        if not s:
            s = Sector.objects.filter(nome__icontains=sec_clean).first()
        if not s:
            norm_sec = normalizar_texto(sec_clean)
            for s_cand in Sector.objects.all():
                norm_cand = normalizar_texto(s_cand.nome)
                if norm_sec and (norm_sec in norm_cand or norm_cand in norm_sec):
                    sector = s_cand
                    break
        else:
            sector = s

    return machine, sector


def extrair_dados_os_por_foto(
    image_file_or_bytes: Any, 
    api_key: Optional[str] = None, 
    model_name: Optional[str] = None, 
    timeout: int = 25
) -> Dict[str, Any]:
    """
    Envia a foto da OS para a API do Google Gemini Vision e extrai os campos estruturados em JSON.
    """
    # 1. Obter chave de API
    if api_key is None:
        api_key = getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    api_key = api_key.strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY não configurada no servidor.")
        return {
            "sucesso": False,
            "motivo": "CHAVE_NAO_CONFIGURADA",
            "mensagem": "Chave da API Gemini não configurada no servidor. Preencha os campos manualmente."
        }

    # 2. Obter bytes e inferir mime_type
    try:
        if hasattr(image_file_or_bytes, "read"):
            if hasattr(image_file_or_bytes, "seek"):
                image_file_or_bytes.seek(0)
            img_bytes = image_file_or_bytes.read()
            content_type = getattr(image_file_or_bytes, "content_type", "")
        elif isinstance(image_file_or_bytes, bytes):
            img_bytes = image_file_or_bytes
            content_type = ""
        else:
            return {
                "sucesso": False,
                "motivo": "ARQUIVO_INVALIDO",
                "mensagem": "Formato de arquivo de imagem não reconhecido."
            }

        if not img_bytes:
            return {
                "sucesso": False,
                "motivo": "ARQUIVO_VAZIO",
                "mensagem": "O arquivo de imagem enviado está vazio."
            }

        if not content_type:
            if img_bytes.startswith(b'\x89PNG'):
                content_type = "image/png"
            elif img_bytes.startswith(b'RIFF') and b'WEBP' in img_bytes[:12]:
                content_type = "image/webp"
            else:
                content_type = "image/jpeg"

        b64_data = base64.b64encode(img_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"Erro ao processar imagem para envio ao Gemini: {e}")
        return {
            "sucesso": False,
            "motivo": "ERRO_PROCESSAMENTO_IMAGEM",
            "mensagem": f"Erro ao preparar imagem para leitura: {str(e)}"
        }

    # 3. Chamar API REST do Google Gemini (com fallback inteligente de modelos)
    primary_model = (model_name or getattr(settings, "GEMINI_MODEL", "") or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")).strip() or "gemini-3.5-flash"
    fallback_pool = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]
    models_to_try = [primary_model] + [m for m in fallback_pool if m != primary_model]

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT_ESPECIALISTA_OS},
                    {
                        "inline_data": {
                            "mime_type": content_type,
                            "data": b64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }

    resp = None
    last_error_status = 500
    last_error_text = ""

    for current_model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                resp = r
                break
            else:
                last_error_status = r.status_code
                last_error_text = r.text
                logger.warning(f"Modelo Gemini '{current_model}' retornou status {r.status_code}. Tentando modelo alternativo se disponível...")
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout ao consultar modelo Gemini '{current_model}'.")
            return {
                "sucesso": False,
                "motivo": "TIMEOUT",
                "mensagem": "Tempo limite excedido ao consultar o serviço de IA. Preencha os campos manualmente."
            }
        except requests.exceptions.RequestException as net_err:
            logger.warning(f"Erro de conexão com Gemini API ({current_model}): {net_err}")
            return {
                "sucesso": False,
                "motivo": "FALHA_CONEXAO",
                "mensagem": "Não foi possível conectar ao serviço de IA. Verifique sua conexão à internet."
            }

    if resp is None:
        logger.error(f"Todos os modelos Gemini falharam. Último status {last_error_status}: {last_error_text}")
        return {
            "sucesso": False,
            "motivo": "ERRO_API",
            "status_code": last_error_status,
            "mensagem": f"Falha na comunicação com o serviço de IA (código {last_error_status}). Preencha os campos manualmente."
        }


    try:
        resp_data = resp.json()
        candidates = resp_data.get("candidates", [])
        if not candidates:
            return {
                "sucesso": False,
                "motivo": "RESPOSTA_VAZIA",
                "mensagem": "Nenhuma informação foi extraída pela IA. Preencha os campos manualmente."
            }

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return {
                "sucesso": False,
                "motivo": "RESPOSTA_VAZIA",
                "mensagem": "Nenhuma informação foi extraída pela IA."
            }

        raw_text = parts[0].get("text", "").strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)
            raw_text = raw_text.strip()

        dados_json = json.loads(raw_text)

        # 4. Realizar casamento com banco de dados
        maq_texto = dados_json.get("descricao_equipamento") or ""
        tag_texto = dados_json.get("tag") or ""
        setor_texto = dados_json.get("setor_texto") or ""

        machine_obj, sector_obj = casar_maquina_e_setor(maq_texto, tag_texto, setor_texto)

        return {
            "sucesso": True,
            "dados": dados_json,
            "maquina_sugerida_id": machine_obj.id if machine_obj else None,
            "maquina_sugerida_nome": machine_obj.nome if machine_obj else None,
            "setor_sugerido_id": sector_obj.id if sector_obj else None,
            "setor_sugerido_nome": sector_obj.nome if sector_obj else None,
        }

    except requests.exceptions.Timeout:
        logger.warning("Timeout ao chamar Gemini API.")
        return {
            "sucesso": False,
            "motivo": "TIMEOUT",
            "mensagem": "Tempo limite excedido ao consultar o serviço de IA. Preencha os campos manualmente."
        }
    except requests.exceptions.RequestException as re_err:
        logger.warning(f"Erro de conexão com Gemini API: {re_err}")
        return {
            "sucesso": False,
            "motivo": "FALHA_CONEXAO",
            "mensagem": "Não foi possível conectar ao serviço de IA. Verifique sua conexão à internet."
        }
    except json.JSONDecodeError as json_err:
        logger.error(f"Erro ao decodificar JSON retornado pelo Gemini: {json_err} | Texto: {raw_text}")
        return {
            "sucesso": False,
            "motivo": "JSON_INVALIDO",
            "mensagem": "Não foi possível processar a resposta da IA. Preencha os campos manualmente."
        }
    except Exception as exc:
        logger.exception(f"Erro inesperado no OCR de OS: {exc}")
        return {
            "sucesso": False,
            "motivo": "ERRO_INESPERADO",
            "mensagem": f"Erro interno ao processar leitura: {str(exc)}"
        }
