from django import forms
from django.contrib.auth.models import User
from .models import Sector, Machine, Technician, Allocation, OrdemServico

class SectorForm(forms.ModelForm):
    class Meta:
        model = Sector
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Usinagem, Montagem'}),
        }


class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = ['nome', 'setor', 'criticidade']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Prensa Hidráulica 01'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'criticidade': forms.Select(attrs={'class': 'form-select'}),
        }


class TechnicianForm(forms.ModelForm):
    """Formulário de criação/edição de Técnico.

    Campos extras (não-model) para criação de usuário de chão de fábrica:
      - username_login : login desejado (opcional; se preenchido, cria/atualiza User)
      - senha_acesso   : senha simples (mínimo 4 caracteres; validadores complexos desativados)
      - perfil_acesso  : TECNICO (apenas próprio card) ou OPERADOR (acesso total)
    """

    username_login = forms.CharField(
        required=False,
        label="Login (Username)",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: joao.silva  (deixe em branco para não criar acesso)',
            'autocomplete': 'off',
        }),
        help_text="Deixe em branco se o técnico não precisar de acesso ao sistema."
    )
    senha_acesso = forms.CharField(
        required=False,
        label="Senha de Acesso",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mínimo 4 caracteres',
            'autocomplete': 'new-password',
        }),
        help_text="Senha simplificada para uso em chão de fábrica (mín. 4 caracteres). Deixe em branco para manter a senha atual."
    )
    perfil_acesso = forms.ChoiceField(
        required=False,
        label="Perfil de Acesso",
        choices=[
            ('TECNICO', 'Técnico — Acesso apenas ao próprio card'),
            ('TECNICO_LIDER', 'Técnico Líder — Acesso ao painel e dashboard (sem cadastros)'),
            ('OPERADOR', 'Operador/Administrador — Acesso total (dashboard, cadastros e todos os cards)'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='TECNICO',
    )



    class Meta:
        model = Technician
        fields = ['nome', 'matricula', 'whatsapp', 'is_active']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: João Silva'}),
            'matricula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: TEC-12345'}),
            'whatsapp': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 31999999999'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        is_active = cleaned_data.get('is_active')
        if self.instance and self.instance.pk and is_active is False:
            if self.instance.allocations.filter(data_fim__isnull=True).exists():
                raise forms.ValidationError(
                    "O técnico possui atendimentos em aberto. Conclua ou transfira os atendimentos antes de inativá-lo."
                )
        return cleaned_data

    def clean_username_login(self):
        username = self.cleaned_data.get('username_login', '').strip()
        if not username:
            return username
        # Verifica unicidade: exclui o próprio usuário vinculado ao técnico (caso de edição)
        qs = User.objects.filter(username=username)
        if self.instance and self.instance.pk and self.instance.user:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError(f"O username '{username}' já está em uso. Escolha outro.")
        return username

    def clean_senha_acesso(self):
        senha = self.cleaned_data.get('senha_acesso', '').strip()
        if senha and len(senha) < 4:
            raise forms.ValidationError("A senha deve ter pelo menos 4 caracteres.")
        return senha


class StartServiceForm(forms.ModelForm):
    class Meta:
        model = Allocation
        fields = ['maquina', 'atividade_observacao']
        widgets = {
            'maquina': forms.Select(attrs={'class': 'form-select', 'required': 'required'}),
            'atividade_observacao': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Descreva detalhadamente a atividade a ser realizada...',
                'required': 'required'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Otimizar queryset com select_related('setor') e ordenar por nome da máquina
        self.fields['maquina'].queryset = Machine.objects.select_related('setor').order_by('nome')
        # Exibição combinando nome da máquina e setor
        self.fields['maquina'].label_from_instance = lambda obj: f"{obj.nome} [Setor: {obj.setor.nome}]"
        # Ensure machine field is required
        self.fields['maquina'].required = True
        self.fields['atividade_observacao'].required = True


class PauseServiceForm(forms.ModelForm):
    class Meta:
        model = Allocation
        fields = ['motivo_pausa']
        widgets = {
            'motivo_pausa': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Descreva obrigatoriamente o motivo da pausa...',
                'required': 'required'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['motivo_pausa'].required = True


class FinishServiceForm(forms.ModelForm):
    foto_conclusao = forms.ImageField(
        required=False,
        label="Foto da Folha de OS Concluída e Assinada",
        widget=forms.FileInput(attrs={
            'class': 'form-control', 
            'accept': 'image/*', 
            'capture': 'environment',
            'id': 'id_foto_conclusao'
        })
    )
    foto_verso = forms.ImageField(
        required=False,
        label="Foto do Verso da OS (Opcional)",
        widget=forms.FileInput(attrs={
            'class': 'form-control', 
            'accept': 'image/*', 
            'capture': 'environment',
            'id': 'id_foto_verso'
        })
    )
    lider_assinatura_nome = forms.CharField(
        required=False,
        max_length=120,
        label="Nome do Líder que Assinou a OS",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Líder Roberto Santos',
            'id': 'id_lider_assinatura_nome'
        })
    )
    causa = forms.CharField(
        required=False,
        label="Causa Raiz / Defeito Identificado",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Descreva a causa encontrada na máquina...',
            'id': 'id_causa'
        })
    )
    descricao_servico_realizado = forms.CharField(
        required=False,
        label="Descrição do Serviço Realizado",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Descreva o serviço executado detalhadamente...',
            'id': 'id_descricao_servico_realizado'
        })
    )
    pecas_utilizadas_texto = forms.CharField(
        required=False,
        label="Peças / Materiais Utilizados",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ex: 2x Rolamento 6204 DDU, 1x Retentor 35x50x8',
            'id': 'id_pecas_utilizadas_texto'
        })
    )

    class Meta:
        model = Allocation
        fields = ['observacao_conclusao', 'foto_anexo']
        widgets = {
            'observacao_conclusao': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Descreva o que foi concluído na manutenção...',
                'required': 'required',
            }),
            'foto_anexo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['observacao_conclusao'].required = True
        self.fields['observacao_conclusao'].error_messages = {
            'required': 'A observação de conclusão é obrigatória para encerrar o serviço.'
        }



class OrdemServicoCreateForm(forms.ModelForm):
    """
    Formulário de abertura/cadastro de Ordem de Serviço física com suporte a
    captura de foto obrigatória, validação estrita anti-duplicidade e campos da folha industrial.
    """
    parou_maquina = forms.TypedChoiceField(
        coerce=lambda x: str(x).lower() in ['true', '1', 'sim'],
        choices=[(True, 'SIM — Máquina Parada / Inoperante'), (False, 'NÃO — Em Operação / Rodando')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_parou_maquina'}),
        initial=True,
        required=False,
        label="Parou a Máquina?"
    )

    class Meta:
        model = OrdemServico
        fields = [
            'numero_os',
            'tag',
            'descricao_equipamento',
            'setor',
            'maquina',
            'solicitante',
            'motivo',
            'tipo_manutencao',
            'parou_maquina',
            'criticidade',
            'descricao_falha',
            'data_hora_inicio_ocorrencia',
            'tecnico_designado',
            'foto_abertura',
        ]
        widgets = {
            'numero_os': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace fw-bold',
                'placeholder': 'Ex: 10216',
                'autocomplete': 'off',
                'id': 'id_numero_os'
            }),
            'tag': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: PREN-01 ou 102',
                'id': 'id_tag'
            }),
            'descricao_equipamento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Prensa Vulcanizadora 10',
                'id': 'id_descricao_equipamento'
            }),
            'setor': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_setor'
            }),
            'maquina': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_maquina'
            }),
            'solicitante': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nome do líder / solicitante',
                'id': 'id_solicitante'
            }),
            'motivo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Vazamento de vapor, esteira travada',
                'id': 'id_motivo'
            }),
            'tipo_manutencao': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_tipo_manutencao'
            }),

            'criticidade': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_criticidade'
            }),
            'descricao_falha': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Descreva detalhadamente o serviço a ser realizado e o defeito relatado...',
                'id': 'id_descricao_falha'
            }),
            'data_hora_inicio_ocorrencia': forms.DateTimeInput(
                attrs={
                    'class': 'form-control',
                    'type': 'datetime-local',
                    'id': 'id_data_hora_inicio_ocorrencia'
                },
                format='%Y-%m-%dT%H:%M'
            ),
            'tecnico_designado': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_tecnico_designado'
            }),
            'foto_abertura': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'id': 'id_foto_abertura'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['numero_os'].required = True
        self.fields['solicitante'].required = True
        self.fields['descricao_falha'].required = True
        self.fields['foto_abertura'].required = True
        self.fields['foto_abertura'].error_messages['required'] = 'A foto da folha física de abertura da OS é obrigatória.'

        self.fields['maquina'].queryset = Machine.objects.select_related('setor').order_by('nome')
        self.fields['maquina'].label_from_instance = lambda obj: f"{obj.nome} [{obj.setor.nome}]"
        self.fields['setor'].queryset = Sector.objects.all().order_by('nome')
        self.fields['tecnico_designado'].queryset = Technician.objects.filter(is_active=True).order_by('nome')
        self.fields['data_hora_inicio_ocorrencia'].input_formats = [
            '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M'
        ]

    def clean_numero_os(self):
        numero = self.cleaned_data.get('numero_os', '').strip().upper()
        if not numero:
            raise forms.ValidationError("O número da Ordem de Serviço física é obrigatório.")
        qs = OrdemServico.objects.filter(numero_os__iexact=numero)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            os_existente = qs.first()
            raise forms.ValidationError(
                f"A OS nº {numero} já está cadastrada (Criada em {os_existente.data_abertura.strftime('%d/%m/%Y')} - Status: {os_existente.get_status_display()})."
            )
        return numero

    def clean_foto_abertura(self):
        foto = self.cleaned_data.get('foto_abertura')
        if not foto:
            raise forms.ValidationError("A foto da folha física de abertura da OS é obrigatória.")
        return foto

