from django import forms
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
    class Meta:
        model = Technician
        fields = ['nome', 'matricula']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: João Silva'}),
            'matricula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: TEC-12345'}),
        }


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
                'placeholder': 'Descreva o que foi concluído na manutenção...'
            }),
            'foto_anexo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
