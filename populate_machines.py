import os
import sys
import django
import pandas as pd

# Configuração do ambiente Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maintenance_project.settings")
django.setup()

from maintenance.models import Sector, Machine

def map_criticidade(val):
    """
    Mapeia a criticidade da planilha para as opções do modelo: 'BAIXA', 'MEDIA', 'ALTA'.
    """
    if val is None or pd.isna(val):
        return 'BAIXA'
    val_lower = str(val).lower().strip()
    if 'alta' in val_lower or 'grave' in val_lower or 'urgente' in val_lower:
        return 'ALTA'
    elif 'media' in val_lower or 'média' in val_lower or 'med' in val_lower:
        return 'MEDIA'
    else:
        return 'BAIXA'

def clean_value(val):
    """
    Limpa o valor lido do Excel, removendo espaços e garantindo representação string correta.
    Previne que números inteiros sejam representados como float (ex: 102 -> 102.0).
    """
    if val is None or pd.isna(val):
        return ""
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val)).strip()
    return str(val).strip()

def populate():
    excel_path = 'TAG DAS MÁQUINAS.xlsx'
    if not os.path.exists(excel_path):
        print(f"Erro: O arquivo '{excel_path}' não foi encontrado na raiz do projeto.")
        sys.exit(1)
        
    print(f"Lendo planilha: '{excel_path}'...")
    try:
        # Carrega a planilha usando Pandas com a segunda linha (index 1) como cabeçalho
        df = pd.read_excel(excel_path, sheet_name='Cronograma 2026', header=1)
    except Exception as e:
        print(f"Erro ao abrir arquivo Excel: {e}")
        sys.exit(1)
        
    # Identificar dinamicamente as colunas com base no conteúdo
    col_maquina = next((c for c in df.columns if 'equipamento' in str(c).lower() or 'maquina' in str(c).lower() or 'máquina' in str(c).lower() or 'nome' in str(c).lower()), None)
    col_setor = next((c for c in df.columns if 'setor' in str(c).lower()), None)
    col_tag = next((c for c in df.columns if 'tag' in str(c).lower()), None)
    col_criticidade = next((c for c in df.columns if 'criticidade' in str(c).lower() or 'prioridade' in str(c).lower() or 'crit' in str(c).lower()), None)
    
    if not col_maquina or not col_setor:
        print("Erro: Não foi possível mapear as colunas cruciais 'Nome do Equipamento' e/ou 'Setor' na planilha.")
        sys.exit(1)
        
    print(f"Mapeamento de Colunas - Máquina: '{col_maquina}', Setor: '{col_setor}', Tag: '{col_tag}', Criticidade: '{col_criticidade}'")
    
    # 1. LIMPEZA DE LINHAS EM BRANCO (EVITAR SETORES FANTASMAS)
    # Remove linhas onde Setor ou Máquina (Nome do Equipamento) são nulas/NaN
    df = df.dropna(subset=[col_maquina, col_setor])
    
    # Limpa strings e filtra valores vazios ("") ou strings 'nan'
    df_filtered_rows = []
    for idx, row in df.iterrows():
        nome_maq = clean_value(row[col_maquina])
        nome_setor = clean_value(row[col_setor])
        tag = clean_value(row[col_tag]) if col_tag else ""
        
        # Ignora se vazio, nan string, ou se for a própria linha de cabeçalho duplicada
        if not nome_maq or not nome_setor or nome_maq.lower() == 'nan' or nome_setor.lower() == 'nan':
            continue
            
        if nome_maq.lower() in ['nome do equipamento', 'máquina', 'maquina'] or nome_setor.lower() == 'setor' or tag.lower() == 'tag':
            continue
            
        df_filtered_rows.append(row)
        
    if not df_filtered_rows:
        print("\n--- Relatório de Importação ---")
        print(f"Total de Setores criados/encontrados: {Sector.objects.count()}")
        print(f"Total de Máquinas importadas com sucesso: 0")
        print("---------------------------------")
        return
        
    df_clean = pd.DataFrame(df_filtered_rows)
    total_machines_success = 0
    
    # Iterar sobre as linhas limpas e cadastrá-las/atualizá-las
    for index, row in df_clean.iterrows():
        try:
            nome_maquina_limpo = clean_value(row[col_maquina])
            nome_setor_limpo = clean_value(row[col_setor])
            criticidade_raw = row[col_criticidade] if col_criticidade else 'BAIXA'
            mapeamento_criticidade = map_criticidade(criticidade_raw)
            
            # Buscar ou criar o Setor (fidelidade total no nome)
            setor_obj, _ = Sector.objects.get_or_create(nome=nome_setor_limpo)
            
            # Cadastrar ou Buscar a Máquina comparando tanto Nome quanto o Setor
            maquina_obj, created = Machine.objects.get_or_create(
                nome=nome_maquina_limpo,
                setor=setor_obj,
                defaults={'criticidade': mapeamento_criticidade}
            )
            
            # Atualiza criticidade se já existir e for diferente
            if not created:
                if maquina_obj.criticidade != mapeamento_criticidade:
                    maquina_obj.criticidade = mapeamento_criticidade
                    maquina_obj.save()
            
            total_machines_success += 1
            
        except Exception as e:
            nome_maq_err = clean_value(row[col_maquina]) if col_maquina in row else "Desconhecido"
            print(f"Erro ao importar máquina '{nome_maq_err}' na linha {index + 3}: {e}")
            
    # Feedback no Terminal
    print("\n--- Relatório de Importação ---")
    print(f"Total de Setores criados/encontrados: {Sector.objects.count()}")
    print(f"Total de Máquinas importadas com sucesso: {total_machines_success}")
    print("---------------------------------")

if __name__ == "__main__":
    populate()
