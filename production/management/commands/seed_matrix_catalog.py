from django.core.management.base import BaseCommand
from production.models import ProductionMatrixCatalog

MATRIZES_SCADA = {
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
    43: "PNEU SPEEDY 2.75-18 S/C",
}


class Command(BaseCommand):
    help = "Carga idempotente dos 43 modelos canônicos de matrizes/produtos do SCADA"

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for code, name in MATRIZES_SCADA.items():
            str_code = str(code)
            obj = ProductionMatrixCatalog.objects.filter(codigo_scada=code).first()
            if not obj:
                obj = ProductionMatrixCatalog.objects.filter(codigo=str_code).first()

            if not obj:
                ProductionMatrixCatalog.objects.create(
                    codigo_scada=code,
                    codigo=str_code,
                    nome_scada=name,
                    nome_exibicao=name,
                    produto=name,
                    descricao=name,
                    ativo=True
                )
                created_count += 1
            else:
                updated = False
                if obj.codigo_scada != code:
                    obj.codigo_scada = code
                    updated = True
                if not obj.nome_scada:
                    obj.nome_scada = name
                    updated = True
                if not obj.nome_exibicao:
                    obj.nome_exibicao = name
                    updated = True
                if not obj.produto:
                    obj.produto = name
                    updated = True
                if updated:
                    obj.save()
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo canônico processado: {created_count} criados, {updated_count} atualizados, "
                f"total no banco: {ProductionMatrixCatalog.objects.count()}"
            )
        )
