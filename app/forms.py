from django import forms


class PetForm(forms.Form):
    photo = forms.ImageField()
