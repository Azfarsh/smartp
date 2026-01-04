from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User, Group
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.hashers import make_password
from .admin_forms import CustomUserCreationForm, CustomUserChangeForm
from .views import create_or_update_admin_user_in_d1


# Unregister Group and User from admin (they are registered by default)
admin.site.unregister(Group)
admin.site.unregister(User)


# Signal to sync User to D1 database
@receiver(post_save, sender=User)
def sync_user_to_d1(sender, instance, created, **kwargs):
    """Sync Django User to D1 database when saved"""
    try:
        # Get password hash
        password_hash = instance.password if hasattr(instance, 'password') and instance.password else ''
        
        # If password is not hashed, hash it
        if password_hash and not password_hash.startswith('pbkdf2_') and not password_hash.startswith('bcrypt'):
            password_hash = make_password(password_hash)
        
        # Get permissions from form if available
        permissions = None
        if hasattr(instance, '_permissions'):
            permissions = instance._permissions
        
        # Sync to D1
        create_or_update_admin_user_in_d1(
            username=instance.username,
            password_hash=password_hash,
            email=instance.email,
            first_name=instance.first_name,
            last_name=instance.last_name,
            is_superuser=instance.is_superuser,
            is_staff=instance.is_staff,
            is_active=instance.is_active,
            permissions=permissions
        )
        print(f"✅ Synced user {instance.username} to D1 database")
    except Exception as e:
        print(f"❌ Error syncing user {instance.username} to D1: {e}")


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """Custom User Admin with simplified fields, permissions, and D1 sync"""
    
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    # Remove groups and user_permissions from fieldsets
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
        (
            _("Dashboard Access Permissions"),
            {
                "fields": (
                    "can_view_users",
                    "can_view_vendors",
                    "can_view_transactions",
                    "can_view_contacts",
                    "can_view_activity",
                    "can_view_overview_cards",
                ),
                "classes": ("collapse",),
                "description": "Control which sections of the admin dashboard this user can access"
            },
        ),
        (_("Important dates"), {"fields": ("date_joined",)}),  # Removed last_login
    )
    
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
        (
            _("Personal info"),
            {
                "fields": ("first_name", "last_name", "email"),
            },
        ),
        (
            _("Permissions"),
            {
                "fields": ("is_active", "is_staff", "is_superuser"),
            },
        ),
        (
            _("Dashboard Access Permissions"),
            {
                "fields": (
                    "can_view_users",
                    "can_view_vendors",
                    "can_view_transactions",
                    "can_view_contacts",
                    "can_view_activity",
                    "can_view_overview_cards",
                ),
                "classes": ("collapse",),
                "description": "Control which sections of the admin dashboard this user can access"
            },
        ),
    )
    
    def get_fieldsets(self, request, obj=None):
        """Return fieldsets based on whether we're adding or editing"""
        if not obj:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)
    
    def get_form(self, request, obj=None, **kwargs):
        """Use custom form during user creation and editing"""
        defaults = {}
        if obj is None:
            defaults["form"] = self.add_form
        else:
            defaults["form"] = self.form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)
    
    # Remove groups and user_permissions from list_filter
    list_filter = ("is_staff", "is_superuser", "is_active")
    
    # Remove filter_horizontal for groups and user_permissions
    filter_horizontal = ()
    
    # Display fields in list view
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_superuser", "is_active")
    
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)
    
    def save_model(self, request, obj, form, change):
        """Override save to ensure staff users are saved correctly and sync to D1"""
        # If creating a new user and is_staff is True, ensure it's saved
        if not change and obj.is_staff:
            obj.is_active = True  # Staff users should be active
        
        # Get permissions from form
        if hasattr(form, 'get_permissions_dict'):
            permissions = form.get_permissions_dict()
            # Store permissions on instance for signal
            obj._permissions = permissions
        
        # Save the user
        super().save_model(request, obj, form, change)
        
        # Sync to D1 (signal will handle this, but we can also do it here for immediate sync)
        try:
            password_hash = obj.password if hasattr(obj, 'password') and obj.password else ''
            permissions = getattr(obj, '_permissions', None)
            
            create_or_update_admin_user_in_d1(
                username=obj.username,
                password_hash=password_hash,
                email=obj.email,
                first_name=obj.first_name,
                last_name=obj.last_name,
                is_superuser=obj.is_superuser,
                is_staff=obj.is_staff,
                is_active=obj.is_active,
                permissions=permissions
            )
        except Exception as e:
            print(f"❌ Error syncing user to D1 in save_model: {e}")
