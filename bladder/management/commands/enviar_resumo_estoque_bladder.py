from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from bladder.services import enviar_resumo_whatsapp_estoque, gerar_texto_resumo_estoque_whatsapp
from bladder.whatsapp import consultar_envios


class Command(BaseCommand):
    help = "Verifica o horário configurado e envia no máximo um resumo diário do Bladder."

    def add_arguments(self, parser):
        parser.add_argument('--verificar-instalacao', action='store_true', help='Valida produção sem executar consultas HTTP ou envios.')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Executa a compilação do resumo e simula o envio sem efetuar requisições HTTP reais ao microserviço Baileys.',
        )
        parser.add_argument(
            '--preview',
            action='store_true',
            help='Apenas imprime a mensagem formatada no terminal.',
        )

    def handle(self, *args, **options):
        if options.get('verificar_instalacao'):
            if settings.DEBUG or settings.WHATSAPP_DRY_RUN:
                raise CommandError('O agendamento exige DEBUG=False e WHATSAPP_DRY_RUN=False no servidor.')
            self.stdout.write('Ambiente de produção verificado. Nenhum envio executado.')
            return
        dry_run = options.get('dry_run', False)
        preview = options.get('preview', False)

        if preview:
            texto = gerar_texto_resumo_estoque_whatsapp()
            self.stdout.write(self.style.NOTICE("=== PRÉVIA DO RESUMO DE ESTOQUE WHATSAPP ==="))
            self.stdout.write(texto)
            return

        if not dry_run and not settings.DEBUG and not settings.WHATSAPP_DRY_RUN:
            consultar_envios()
        resultado = enviar_resumo_whatsapp_estoque(dry_run=dry_run)
        status = resultado.get('status')

        if status == 'sucesso':
            self.stdout.write(self.style.SUCCESS(f"Resumo enviado com sucesso (HTTP {resultado.get('http_code')})."))
        elif status == 'simulado':
            self.stdout.write(self.style.WARNING(f"[DRY-RUN] Simulação concluída com sucesso para {resultado.get('destino')}."))
            self.stdout.write(resultado.get('texto', ''))
        elif status == 'ja_enviado':
            self.stdout.write(self.style.NOTICE("Resumo já enviado hoje. Envio repetido abortado para evitar spam."))
        elif status == 'fora_do_calendario':
            self.stdout.write(self.style.NOTICE("Envio não programado para hoje (fim de semana ou dia desabilitado)."))
        elif status == 'sem_destinatario':
            self.stdout.write(self.style.WARNING("Configuração ativa sem grupo ou número destinatário definido."))
        elif status == 'desabilitado':
            self.stdout.write(self.style.NOTICE("Envio de resumo está desabilitado na configuração."))
        else:
            self.stdout.write(f"{status}: {resultado.get('mensagem', '')}")

