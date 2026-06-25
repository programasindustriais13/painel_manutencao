from django import forms
from django.contrib.auth.models import User
from .models import Sector, Machine, Technician, Allocation

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
        fields = ['nome', 'matricula', 'whatsapp']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: João Silva'}),
            'matricula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: TEC-12345'}),
            'whatsapp': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 31999999999'}),
        }

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
