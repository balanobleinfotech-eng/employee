from django import forms
from .models import Department, Designation, Branch

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Information Technology'}),
            'code': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. IT'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Optional department description...'}),
        }

class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = ['department', 'title', 'description']
        widgets = {
            'department': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Senior Software Engineer'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Role responsibilities...'}),
        }

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'code', 'address', 'latitude', 'longitude', 'radius_meters', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Netcom Head Office Bangalore', 'required': 'required'}),
            'code': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. BLR-HQ', 'required': 'required'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Office street address / campus details...'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.000001', 'placeholder': '12.971600', 'id': 'branchLatitudeInput', 'required': 'required'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.000001', 'placeholder': '77.594600', 'id': 'branchLongitudeInput', 'required': 'required'}),
            'radius_meters': forms.NumberInput(attrs={'class': 'form-input', 'min': '10', 'max': '5000', 'placeholder': '100', 'required': 'required'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
