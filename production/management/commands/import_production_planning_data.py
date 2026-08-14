import os
import re
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from production.models import (
    ProductionMatrixCatalog,
    ProductionMatrixSize,
    ProductionBladder,
    ProductionPCPSetting,
)

MATRIZES_SCADA_LEGADAS = {
    1: "PNEUS WINGS 90/90-18",
    2: "PNEUS WINGS 2.75-18",
    3: "PNEUS HOPPER 90/90-18",
    4: "PNEUS HOPPER 2.75-18",
    5: "PNEUS READY 110/90-18",
    6: "PNEUS HOPPER 4.10-18",
    7: "PNEUS HOPPER 110/90-17",
    8: "PNEU HOPPER 90/90-19",
    9: "PNEUS WINGS 80/100-14",
    10: "PNEUS WINGS 60/100-17",
    11: "PNEUS READY 90/90-18",
    12: "PNEU READY 2.75-17",
    13: "PNEU READY 110/80-14",
    14: "PNEU OPTION 90/90-18",
    15: "PNEU HOPPER 4.80/4.00-08",
    16: "PNEU HOPPER 80/100-14",
    17: "PNEU HOPPER 2.50-17",
    18: "PNEU SPEEDY 90/90-18",
    19: "PNEU SPEEDY 2.75-18",
    20: "PNEU ROBOT 3.25-08",
    21: "PNEU HOPPER 2.75-17",
    22: "PNEU HOPPER 120/80-18",
    23: "PNEU HOPPER 90/90-21",
    24: "PNEU WINTER 100/100-18",
    25: "PNEU WINTER 90/90-21",
    26: "PNEU HOPPER 100/90-18",
    27: "PNEU HOPPER 80/100-18",
    28: "PNEU SPEEDY 100/90-18",
    29: "PNEU READY 100/90-18",
    30: "PNEU READY 80/100-18",
    31: "PNEU HOPPER 100/80-18",
    32: "PNEU HOPPER 100/90-18 S/C",
    33: "PNEU HOPPER 80/100-18 S/C",
    34: "PNEU SPEEDY 100/90-18 S/C",
    35: "PNEU READY 100/90-18 S/C",
    36: "PNEU READY 80/100-18 S/C",
    37: "PNEU HOPPER 90/90-18 S/C",
    38: "PNEU HOPPER 2.75-18 S/C",
    39: "PNEU READY 90/90-18 S/C",
    40: "PNEU WINGS 90/90-18 S/C",
    41: "PNEU WINGS 2.75-18 S/C",
    42: "PNEU SPEEDY 90/90-18 S/C",
    43: "PNEU SPEEDY 2.75-18 S/C"
}


def norm_string(text):
    if not text or pd.isna(text):
        return ""
    t = str(text).strip().upper()
    t = t.replace("PNEUS ", "PNEU ")
    t = re.sub(r"-0(\d)\b", r"-\1", t)
    t = re.sub(r"\.00-0(\d)\b", r".00-\1", t)
    t = re.sub(r"\s+", " ", t)
    return t


def clean_size_string(s):
    if not s or pd.isna(s):
        return "", ""
    s = str(s).strip()
    s = re.sub(r"^[^\d]+", "", s)
    s = s.upper().strip()
    s = re.sub(r"\s+", " ", s)
    s_compact = s.replace(" ", "")
    s_compact = re.sub(r"-0(\d)\b", r"-\1", s_compact)
    s_compact = re.sub(r"\.00-0(\d)\b", r".00-\1", s_compact)
    return s, s_compact


def extract_size_from_model(model_name):
    m = str(model_name).strip()
    is_sc = bool(re.search(r"\s+S/C$", m, flags=re.I))
    m = re.sub(r"^PNEUS?\s+", "", m, flags=re.I)
    m = re.sub(r"\s+S/C$", "", m, flags=re.I)
    brands = ["WINGS", "HOPPER", "READY", "OPTION", "SPEEDY", "WINTER", "ROBOT", "RIVER"]
    for b in brands:
        m = re.sub(r"^" + b + r"\s+", "", m, flags=re.I)
    norm_s, compact_s = clean_size_string(m)
    return norm_s, compact_s, is_sc


class Command(BaseCommand):
    help = "Importação e reconciliação idempotente de dados de PCP a partir do arquivo Excel TEMPO_PRODUCAO_E_COD_BLADDER.xlsx"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="TEMPO_PRODUCAO_E_COD_BLADDER.xlsx",
            help="Caminho para o arquivo Excel de entrada"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa a análise e simulação de importação sem alterar o banco de dados"
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        dry_run = options["dry_run"]

        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR(f"Arquivo de entrada não encontrado: {file_path}"))
            return

        self.stdout.write(self.style.NOTICE(f"=== INICIANDO IMPORTAÇÃO DE DADOS PCP (Dry-Run={dry_run}) ==="))

        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro ao abrir arquivo Excel: {e}"))
            return

        # 1. Garantir Parâmetros Iniciais Globais de PCP
        if not dry_run:
            ProductionPCPSetting.objects.get_or_create(
                chave="intervalo_operacional_segundos",
                defaults={"valor": "90", "descricao": "Intervalo entre ciclos consecutivos em segundos (padrão 90s)"}
            )
            ProductionPCPSetting.objects.get_or_create(
                chave="perda_lixo_percentual",
                defaults={"valor": "0.50", "descricao": "Percentual estimado de Lixo (0,5%)"}
            )
            ProductionPCPSetting.objects.get_or_create(
                chave="perda_ia_percentual",
                defaults={"valor": "1.00", "descricao": "Percentual estimado de Imperfeição Aparente (1,0%)"}
            )

        # 2. Carga e associação da aba COD BLADDER
        df_bl = pd.read_excel(excel_file, sheet_name="COD BLADDER")
        df_bl["COD DE BLADDER"] = df_bl["COD DE BLADDER"].ffill()

        bladders_created = 0
        bladders_updated = 0
        sizes_created = 0

        with transaction.atomic():
            for idx, row in df_bl.iterrows():
                b_code = str(row["COD DE BLADDER"]).strip()
                m_raw = str(row["MEDIDA PNEU/MATRIZ"]).strip()
                size_norm, size_compact = clean_size_string(m_raw)

                if not b_code or b_code.lower() == "nan" or not size_norm:
                    continue

                if not dry_run:
                    size_obj, s_created = ProductionMatrixSize.objects.get_or_create(
                        medida=size_norm,
                        defaults={"medida_normalizada": size_compact, "ativo": True}
                    )
                    if s_created:
                        sizes_created += 1

                    bladder_obj, b_created = ProductionBladder.objects.get_or_create(
                        codigo_bladder=b_code,
                        defaults={"descricao": f"Bladder compatível {b_code}", "ativo": True}
                    )
                    if b_created:
                        bladders_created += 1
                    
                    if not bladder_obj.medidas.filter(id=size_obj.id).exists():
                        bladder_obj.medidas.add(size_obj)
                        bladders_updated += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Processamento de Bladders: {bladders_created} criados, {bladders_updated} atualizados/vinculados, "
                    f"{sizes_created} novas medidas cadastradas."
                )
            )

            # 3. Processamento da aba TEMPO PRODUCAO e Reconciliação SCADA 43 x 55
            df_tp = pd.read_excel(excel_file, sheet_name="TEMPO PRODUCAO")
            
            scada_norm_map = {code: norm_string(name) for code, name in MATRIZES_SCADA_LEGADAS.items()}
            scada_rev_map = {v: k for k, v in scada_norm_map.items()}

            catalog_created = 0
            catalog_updated = 0
            catalog_ignored = 0

            next_new_code = 44

            for idx, row in df_tp.iterrows():
                name_xlsx = str(row["MODELO DE PNEU"]).strip()
                n_xlsx = norm_string(name_xlsx)
                tempo_prod = int(row["TEMPO DE PRODUÇÃO"])
                tempo_vulc = int(row["TEMPO DE VULCANIZAÇÃO (s)"])
                size_norm, size_compact, is_sc = extract_size_from_model(name_xlsx)

                # Reconciliação
                scada_code = scada_rev_map.get(n_xlsx)
                if scada_code:
                    code_str = str(scada_code)
                    assigned_scada_code = scada_code
                else:
                    code_str = str(next_new_code)
                    assigned_scada_code = next_new_code
                    next_new_code += 1

                if dry_run:
                    self.stdout.write(
                        f"[DRY-RUN] Modelo '{name_xlsx}' -> Código {code_str} (SCADA: {assigned_scada_code}), "
                        f"Tempo Prod: {tempo_prod}s, Vulc: {tempo_vulc}s, Medida: '{size_norm}', S/C={is_sc}"
                    )
                    continue

                # Busca tamanho no banco
                size_obj = ProductionMatrixSize.objects.filter(medida_normalizada=size_compact).first()
                if not size_obj and size_norm:
                    size_obj, _ = ProductionMatrixSize.objects.get_or_create(
                        medida=size_norm,
                        defaults={"medida_normalizada": size_compact, "ativo": True}
                    )

                catalog_obj = ProductionMatrixCatalog.objects.filter(codigo_scada=assigned_scada_code).first()
                if not catalog_obj:
                    catalog_obj = ProductionMatrixCatalog.objects.filter(codigo=code_str).first()

                if not catalog_obj:
                    ProductionMatrixCatalog.objects.create(
                        codigo_scada=assigned_scada_code,
                        codigo=code_str,
                        nome_scada=MATRIZES_SCADA_LEGADAS.get(assigned_scada_code, name_xlsx),
                        nome_exibicao=name_xlsx,
                        produto=name_xlsx,
                        descricao=name_xlsx,
                        medida_size=size_obj,
                        medida_str=size_norm,
                        tempo_producao_segundos=tempo_prod,
                        tempo_vulcanizacao_segundos=tempo_vulc,
                        variante_sc=is_sc,
                        ativo=True
                    )
                    catalog_created += 1
                else:
                    updated_fields = []
                    if catalog_obj.codigo_scada != assigned_scada_code:
                        catalog_obj.codigo_scada = assigned_scada_code
                        updated_fields.append("codigo_scada")
                    if catalog_obj.nome_exibicao != name_xlsx:
                        catalog_obj.nome_exibicao = name_xlsx
                        updated_fields.append("nome_exibicao")
                    if catalog_obj.tempo_producao_segundos != tempo_prod:
                        catalog_obj.tempo_producao_segundos = tempo_prod
                        updated_fields.append("tempo_producao_segundos")
                    if catalog_obj.tempo_vulcanizacao_segundos != tempo_vulc:
                        catalog_obj.tempo_vulcanizacao_segundos = tempo_vulc
                        updated_fields.append("tempo_vulcanizacao_segundos")
                    if catalog_obj.medida_str != size_norm:
                        catalog_obj.medida_str = size_norm
                        updated_fields.append("medida_str")
                    if catalog_obj.medida_size != size_obj:
                        catalog_obj.medida_size = size_obj
                        updated_fields.append("medida_size")
                    if catalog_obj.variante_sc != is_sc:
                        catalog_obj.variante_sc = is_sc
                        updated_fields.append("variante_sc")

                    if updated_fields:
                        catalog_obj.save(update_fields=updated_fields)
                        catalog_updated += 1
                    else:
                        catalog_ignored += 1

            if dry_run:
                self.stdout.write(self.style.WARNING("=== SIMULAÇÃO CONCLUÍDA SEM ALTERAÇÕES (DRY-RUN) ==="))
                # Em dry-run faz rollback proposital da transação
                transaction.set_rollback(True)
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"=== RECONCILIAÇÃO E CARGA CONCLUÍDAS ==="
                        f"\nNovos no Catálogo: {catalog_created}"
                        f"\nAtualizados: {catalog_updated}"
                        f"\nSem alterações: {catalog_ignored}"
                        f"\nTotal no Catálogo: {ProductionMatrixCatalog.objects.count()}"
                    )
                )
