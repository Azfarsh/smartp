from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User


class CustomUserCreationForm(UserCreationForm):
    """Custom user creation form with permission fields"""
    
    # Add admin-specific fields (UserCreationForm only has username and password)
    email = forms.EmailField(required=False, label="Email address")
    first_name = forms.CharField(required=False, max_length=150, label="First name")
    last_name = forms.CharField(required=False, max_length=150, label="Last name")
    is_active = forms.BooleanField(required=False, initial=True, label="Active")
    is_staff = forms.BooleanField(required=False, initial=False, label="Staff status")
    is_superuser = forms.BooleanField(required=False, initial=False, label="Superuser status")
    
    # Dashboard content permissions
    can_view_users = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view/edit User Data",
        help_text="Allow access to view and edit user data"
    )
    can_view_vendors = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Vendor Data",
        help_text="Allow access to vendor data section"
    )
    can_view_transactions = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Vendor Transactions",
        help_text="Allow access to vendor transactions section"
    )
    can_view_contacts = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Contact Data",
        help_text="Allow access to contact data section"
    )
    can_view_activity = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Total Activity",
        help_text="Allow access to activity statistics and charts"
    )
    can_view_overview_cards = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Overview Cards",
        help_text="Allow access to overview statistics cards"
    )
    
    class Meta:
        model = User
        fields = ("username", "password1", "password2", "email", "first_name", "last_name", 
                  "is_active", "is_staff", "is_superuser")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show permission fields for staff users
        if 'is_staff' in self.fields:
            self.fields['is_staff'].widget.attrs['onchange'] = 'togglePermissions(this)'
    
    def get_permissions_dict(self):
        """Get permissions as a dictionary"""
        return {
            'can_view_users': self.cleaned_data.get('can_view_users', False),
            'can_view_vendors': self.cleaned_data.get('can_view_vendors', False),
            'can_view_transactions': self.cleaned_data.get('can_view_transactions', False),
            'can_view_contacts': self.cleaned_data.get('can_view_contacts', False),
            'can_view_activity': self.cleaned_data.get('can_view_activity', False),
            'can_view_overview_cards': self.cleaned_data.get('can_view_overview_cards', False),
        }


class CustomUserChangeForm(UserChangeForm):
    """Custom user change form with permission fields"""
    
    # Dashboard content permissions
    can_view_users = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view/edit User Data",
        help_text="Allow access to view and edit user data"
    )
    can_view_vendors = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Vendor Data",
        help_text="Allow access to vendor data section"
    )
    can_view_transactions = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Vendor Transactions",
        help_text="Allow access to vendor transactions section"
    )
    can_view_contacts = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Contact Data",
        help_text="Allow access to contact data section"
    )
    can_view_activity = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Total Activity",
        help_text="Allow access to activity statistics and charts"
    )
    can_view_overview_cards = forms.BooleanField(
        required=False,
        initial=True,
        label="Can view Overview Cards",
        help_text="Allow access to overview statistics cards"
    )
    
    class Meta:
        model = User
        fields = "__all__"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        
        # Load existing permissions from D1 if user exists
        if instance and instance.pk:
            try:
                from .views import get_admin_user_from_d1
                d1_user = get_admin_user_from_d1(instance.username)
                if d1_user and d1_user.get('permissions'):
                    import json
                    permissions = json.loads(d1_user['permissions']) if isinstance(d1_user['permissions'], str) else d1_user['permissions']
                    for key, value in permissions.items():
                        if key in self.fields:
                            self.fields[key].initial = value
            except Exception as e:
                print(f"Error loading permissions from D1: {e}")
        
        # Only show permission fields for staff users
        if 'is_staff' in self.fields:
            self.fields['is_staff'].widget.attrs['onchange'] = 'togglePermissions(this)'
    
    def get_permissions_dict(self):
        """Get permissions as a dictionary"""
        return {
            'can_view_users': self.cleaned_data.get('can_view_users', False),
            'can_view_vendors': self.cleaned_data.get('can_view_vendors', False),
            'can_view_transactions': self.cleaned_data.get('can_view_transactions', False),
            'can_view_contacts': self.cleaned_data.get('can_view_contacts', False),
            'can_view_activity': self.cleaned_data.get('can_view_activity', False),
            'can_view_overview_cards': self.cleaned_data.get('can_view_overview_cards', False),
        }

