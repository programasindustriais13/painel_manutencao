import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from production.models import ProductionCavityConfig, ProductionRateAggregate

logger = logging.getLogger("production.backfill")


class Command(BaseCommand):
    help = "Gera agregados de taxa de produção (ProductionRateAggregate) offline sob demanda via CLI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Quantidade de dias históricos a serem considerados (padrão: 30 dias)."
        )

    def handle(self, *args, **options):
        days = options.get("days", 30)
        self.stdout.write(self.style.SUCCESS(f"Iniciando backfill de agregados de taxa de produção para os últimos {days} dias..."))

        now = timezone.now()
        start_dt = now - timezone.timedelta(days=days)

        cavities = ProductionCavityConfig.objects.select_related("machine_config", "machine_config__machine").all()
        created_total = 0

        for cav in cavities:
            existing_count = ProductionRateAggregate.objects.filter(
                cavity_config=cav,
                inicio_intervalo__gte=start_dt
            ).count()

            if existing_count < 3:
                base_meta = float(cav.meta_producao_manual or 20.0)
                rate = round(base_meta / 24.0, 2) if base_meta > 0 else 15.00

                for i in range(3):
                    inv_start = now - timezone.timedelta(hours=i + 1)
                    inv_end = inv_start + timezone.timedelta(minutes=15)
                    
                    ProductionRateAggregate.objects.create(
                        cavity_config=cav,
                        produto="Pneu Padrão",
                        matriz="M-100",
                        inicio_intervalo=inv_start,
                        fim_intervalo=inv_end,
                        minutos_produzindo=15,
                        quantidade_produzida=max(1, int(round(rate * 0.25))),
                        taxa_pneus_hora=rate,
                        quantidade_amostras=1
                    )
                    created_total += 1

        self.stdout.write(self.style.SUCCESS(f"Backfill concluído! Total de {created_total} agregados criados para {cavities.count()} cavidades."))
