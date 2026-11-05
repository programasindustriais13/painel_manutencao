from django.core.management.base import BaseCommand
from bladder.services import sincronizar_movimentacoes_pendentes_dr201


class Command(BaseCommand):
    help = "Sincroniza movimentações de estoque pendentes com a planilha DR-201 (Google Sheets) via append_row."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando sincronização de movimentações pendentes com a DR-201..."))
        resultado = sincronizar_movimentacoes_pendentes_dr201()
        total = resultado['total']
        sucessos = resultado['sucessos']
        falhas = resultado['falhas']

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nenhuma movimentação pendente. Todas já sincronizadas na DR-201!"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Total verificado: {total} | Sincronizados: {sucessos} | Falhas: {falhas}"))

