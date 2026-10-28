from .models import InvestorInfo
from django import forms
from django.forms import ModelForm
from django.utils.safestring import mark_safe


class InvestorInfoForm(ModelForm):
    class Meta:
        model = InvestorInfo
        fields = ("investor_name", "investor_email", "investor_phone", "investor_investment")

    investor_name = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'full names'}))
    investor_email = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'email address'}))
    investor_phone = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'phone number'}))
    investor_investment = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'investment'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['investor_name'].label = mark_safe('<strong>INVESTOR NAME</strong>').format(self.fields['investor_name'].label)
        self.fields['investor_email'].label = mark_safe('<strong>INVESTOR EMAIL</strong>').format(self.fields['investor_email'].label)
        self.fields['investor_phone'].label = mark_safe('<strong>INVESTOR PHONE</strong>').format(self.fields['investor_phone'].label)
        self.fields['investor_investment'].label = mark_safe('<strong>INVESTOR INVESTMENT</strong>').format(self.fields['investor_investment'].label)