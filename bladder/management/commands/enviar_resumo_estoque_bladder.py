from django.core.management.base import BaseCommand
from bladder.services import enviar_resumo_whatsapp_estoque, gerar_texto_resumo_estoque_whatsapp


class Command(BaseCommand):
    help = "Dispara o resumo matinal de estoque via WhatsApp (segunda a sexta às 07:30)."

    def add_arguments(self, parser):
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
        dry_run = options.get('dry_run', False)
        preview = options.get('preview', False)

        if preview:
            texto = gerar_texto_resumo_estoque_whatsapp()
            self.stdout.write(self.style.NOTICE("=== PRÉVIA DO RESUMO DE ESTOQUE WHATSAPP ==="))
            self.stdout.write(texto)
            return

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
            self.stdout.write(self.style.ERROR(f"Falha no envio: {resultado}"))

