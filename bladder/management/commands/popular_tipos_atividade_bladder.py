from django.core.management.base import BaseCommand
from bladder.models import TipoAtividadeBladder


class Command(BaseCommand):
    help = "Cadastra os tipos padrão de atividades flexíveis do Setor de Bladder."

    def handle(self, *args, **options):
        tipos_padrao = [
            {
                'codigo': 'EXTRUSAO',
                'nome': 'Extrusão',
                'categoria': 'PRODUCAO',
                'descricao': 'Operação de extrusão de bladders conforme programação e OP.',
                'exige_quantidade': True,
                'exige_modelo': True,
                'exige_dados_tecnicos_tarugo': True,
                'exige_observacao': False,
                'exige_conclusao': True,
                'ordem_exibicao': 1,
            },
            {
                'codigo': 'LIMPEZA',
                'nome': 'Limpeza de Bladder',
                'categoria': 'OPERACIONAL',
                'descricao': 'Limpeza periódica, higienização de moldes ou peças.',
                'exige_quantidade': False,
                'exige_modelo': False,
                'exige_dados_tecnicos_tarugo': False,
                'exige_observacao': False,
                'exige_conclusao': True,
                'ordem_exibicao': 2,
            },
            {
                'codigo': 'ORGANIZACAO',
                'nome': 'Organização do Setor',
                'categoria': 'OPERACIONAL',
                'descricao': 'Organização 5S, limpeza de bancadas e arrumação de carrinhos.',
                'exige_quantidade': False,
                'exige_modelo': False,
                'exige_dados_tecnicos_tarugo': False,
                'exige_observacao': False,
                'exige_conclusao': True,
                'ordem_exibicao': 3,
            },
            {
                'codigo': 'MANUTENCAO',
                'nome': 'Manutenção Operacional / Setup',
                'categoria': 'OPERACIONAL',
                'descricao': 'Ajustes mecânicos simples, troca de matriz ou suporte à manutenção.',
                'exige_quantidade': False,
                'exige_modelo': False,
                'exige_dados_tecnicos_tarugo': False,
                'exige_observacao': True,
                'exige_conclusao': True,
                'ordem_exibicao': 4,
            },
            {
                'codigo': 'CORTE_BORRACHA',
                'nome': 'Corte de Borracha',
                'categoria': 'OPERACIONAL',
                'descricao': 'Corte, pesagem e preparação de tiras ou tarugos de borracha crua.',
                'exige_quantidade': False,
                'exige_modelo': False,
                'exige_dados_tecnicos_tarugo': False,
                'exige_observacao': False,
                'exige_conclusao': True,
                'ordem_exibicao': 5,
            },
            {
                'codigo': 'PERSONALIZADA',
                'nome': 'Atividade Personalizada',
                'categoria': 'OPERACIONAL',
                'descricao': 'Atividade livre com relato detalhado do operador.',
                'exige_quantidade': False,
                'exige_modelo': False,
                'exige_dados_tecnicos_tarugo': False,
                'exige_observacao': True,
                'exige_conclusao': True,
                'ordem_exibicao': 6,
            },
        ]

        criados = 0
        atualizados = 0

        for item in tipos_padrao:
            codigo = item.pop('codigo')
            obj, created = TipoAtividadeBladder.objects.update_or_create(
                codigo=codigo,
                defaults=item
            )
            if created:
                criados += 1
            else:
                atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Tipos de atividade processados: {criados} criados, {atualizados} atualizados com sucesso."
            )
        )

