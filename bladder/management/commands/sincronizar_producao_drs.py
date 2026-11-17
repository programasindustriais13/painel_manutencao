from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from bladder.sincronizacao_drs import processar_pendentes


class Command(BaseCommand):
    help = 'Processa a fila persistente das DR.114/115, sem criar campos nas planilhas.'

    def add_arguments(self, parser):
        parser.add_argument('--destino', choices=['DR114', 'DR115'])
        parser.add_argument('--limite', type=int, default=10)
        parser.add_argument('--verificar-instalacao', action='store_true')

    def handle(self, *args, **options):
        if options['verificar_instalacao']:
            if settings.DEBUG:
                raise CommandError('Instale a tarefa apenas no servidor de produção, com DEBUG=False.')
            if not (settings.BASE_DIR / 'credentials.json').is_file():
                raise CommandError('credentials.json não encontrado no servidor.')
            self.stdout.write('Configuração de produção disponível. Nenhum dado foi enviado.')
            return
        if not 1 <= options['limite'] <= 1000:
            raise CommandError('--limite deve estar entre 1 e 1000.')
        total = processar_pendentes(limite=options['limite'], destino=options['destino'])
        self.stdout.write(f'Fila de produção DR.114/115: {total} registro(s) verificado(s).')
