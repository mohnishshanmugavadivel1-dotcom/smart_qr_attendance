from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=User.ROLE_CHOICES, widget=forms.RadioSelect)
    roll_number = forms.CharField(required=False, help_text="Required for students")
    
    class Meta:
        model = User
        fields = ('username', 'email', 'role', 'roll_number', 'password1', 'password2')
    
    def clean(self):
        cleaned = super().clean()
        role = cleaned.get('role')
        roll = cleaned.get('roll_number')
        if role == 'student' and not roll:
            self.add_error('roll_number', 'Roll number is required for students.')
        return cleaned
