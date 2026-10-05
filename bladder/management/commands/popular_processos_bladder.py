import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from maintenance.models import Machine, Sector
from bladder.models import (
    ProcessoBladder,
    ConfiguracaoEscalaBladder,
    RecursoBladder,
)


class Command(BaseCommand):
    help = "Cria ou atualiza os 6 processos padrão do setor de Bladder, recursos e escala padrão de forma idempotente."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando carga de processos e configurações do setor de Bladder..."))

        # Busca máquinas existentes no banco
        setor_bladder = Sector.objects.filter(nome__icontains="BLADDER").first()
        m408 = Machine.objects.filter(nome__icontains="PRENSA DE BLADER 01").first()
        m409 = Machine.objects.filter(nome__icontains="PRENSA DE BLADER 02").first()
        m419 = Machine.objects.filter(nome__icontains="EXTRUSORA DE BLADDER 02").first()

        processos_data = [
            {
                "codigo": "01",
                "nome": "Prensa de Vulcanização 01",
                "tipo": "PRENSA",
                "maquina": m408,
                "ordem_exibicao": 1,
            },
            {
                "codigo": "02",
                "nome": "Prensa de Vulcanização 02",
                "tipo": "PRENSA",
                "maquina": m409,
                "ordem_exibicao": 2,
            },
            {
                "codigo": "03",
                "nome": "Extrusão de Bladder",
                "tipo": "EXTRUSAO",
                "maquina": m419,
                "ordem_exibicao": 3,
            },
            {
                "codigo": "04",
                "nome": "Extrusão de Apex",
                "tipo": "EXTRUSAO",
                "maquina": None,
                "ordem_exibicao": 4,
            },
            {
                "codigo": "05",
                "nome": "Anéis de Vedação",
                "tipo": "ACABAMENTO",
                "maquina": None,
                "ordem_exibicao": 5,
            },
            {
                "codigo": "06",
                "nome": "Manuseio de Tarugo",
                "tipo": "MANUAL",
                "maquina": None,
                "ordem_exibicao": 6,
            },
        ]

        with transaction.atomic(using='default'):
            criados, atualizados = 0, 0
            for p in processos_data:
                obj, created = ProcessoBladder.objects.update_or_create(
                    codigo=p["codigo"],
                    defaults={
                        "nome": p["nome"],
                        "tipo": p["tipo"],
                        "maquina": p["maquina"],
                        "ordem_exibicao": p["ordem_exibicao"],
                        "ativo": True,
                    }
                )
                if created:
                    criados += 1
                else:
                    atualizados += 1

            self.stdout.write(self.style.SUCCESS(f"Processos: {criados} criados, {atualizados} atualizados."))

            # 2. Configuração de Escala Padrão se não existir
            if not ConfiguracaoEscalaBladder.objects.filter(ativo=True).exists():
                ConfiguracaoEscalaBladder.objects.create(
                    data_referencia=timezone.localdate(),
                    turma_referencia="TURMA_A",
                    hora_inicio=datetime.time(6, 0),
                    hora_fim=datetime.time(18, 0),
                    ativo=True,
                    observacoes="Configuração inicial criada automaticamente."
                )
                self.stdout.write(self.style.SUCCESS("Escala 12x36 padrão criada (Turma A / B, 06:00 às 18:00)."))

            # 3. Recursos Iniciais Padrão
            recursos_padrao = [
                {"categoria": "MATRIZ", "codigo": "MAT01", "nome": "Matriz de Extrusão MAT01"},
                {"categoria": "MATRIZ", "codigo": "MAT02", "nome": "Matriz de Extrusão MAT02"},
                {"categoria": "MATRIZ", "codigo": "MAT03", "nome": "Matriz de Extrusão MAT03"},
                {"categoria": "MATRIZ", "codigo": "MAT04", "nome": "Matriz de Extrusão MAT04"},
                {"categoria": "MATRIZ", "codigo": "MAT05", "nome": "Matriz de Extrusão MAT05"},
                {"categoria": "MATRIZ", "codigo": "MAT06", "nome": "Matriz de Extrusão MAT06"},
                {"categoria": "COMPOSTO", "codigo": "COMP-BLA", "nome": "Composto de Borracha para Bladder"},
                {"categoria": "FERRAMENTA", "codigo": "FACA-CHANF", "nome": "Faca de Corte e Chanfro de Tarugo"},
                {"categoria": "MATERIA_PRIMA", "codigo": "TARUGO-BRUTO", "nome": "Tarugo Extrusado Bruto"},
            ]

            rec_criados = 0
            for r in recursos_padrao:
                _, created = RecursoBladder.objects.get_or_create(
                    codigo=r["codigo"],
                    defaults={
                        "categoria": r["categoria"],
                        "nome": r["nome"],
                        "ativo": True,
                    }
                )
                if created:
                    rec_criados += 1

            self.stdout.write(self.style.SUCCESS(f"Recursos: {rec_criados} novos criados."))

        self.stdout.write(self.style.SUCCESS("Processos e configurações carregados com sucesso!"))
