"""
Management command to migrate Django admin users to D1 database
Run: python manage.py migrate_admin_users_to_d1
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from print.views import create_or_update_admin_user_in_d1
import json


class Command(BaseCommand):
    help = 'Migrate Django admin users (superusers and staff) to D1 database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually migrating',
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Migrate only a specific username',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        username_filter = options.get('username')
        
        # Get all admin users (superusers or staff)
        if username_filter:
            users = User.objects.filter(username=username_filter)
        else:
            users = User.objects.filter(is_staff=True) | User.objects.filter(is_superuser=True)
            users = users.distinct()
        
        if not users.exists():
            self.stdout.write(self.style.WARNING('No admin users found to migrate.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {users.count()} admin user(s) to migrate.'))
        
        migrated_count = 0
        failed_count = 0
        
        for user in users:
            try:
                # Get user's password hash from Django
                # Note: We can't retrieve the original password, but we can use the stored hash
                # If the user has a password set, we use it; otherwise we skip
                # Django password hashes start with algorithm identifiers like 'pbkdf2_', 'argon2', etc.
                # Unusable passwords start with '!' or are empty
                if not user.password or (user.password.startswith('!') and len(user.password) == 1):
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping {user.username}: No usable password hash found. '
                            'User may need to reset password.'
                        )
                    )
                    continue
                
                # Prepare permissions (can be extended based on your needs)
                permissions = None
                if user.is_superuser:
                    permissions = {'all_permissions': True}
                else:
                    # Get user permissions
                    perms = user.user_permissions.all()
                    if perms.exists():
                        permissions = {
                            'permissions': [f"{p.content_type.app_label}.{p.codename}" for p in perms]
                        }
                
                user_data = {
                    'username': user.username,
                    'password_hash': user.password,  # Django's password hash format
                    'email': user.email or '',
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'is_superuser': user.is_superuser,
                    'is_staff': user.is_staff,
                    'is_active': user.is_active,
                    'permissions': permissions
                }
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'[DRY RUN] Would migrate: {user.username} '
                            f'(superuser={user.is_superuser}, staff={user.is_staff})'
                        )
                    )
                else:
                    # Migrate to D1
                    success = create_or_update_admin_user_in_d1(**user_data)
                    
                    if success:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ Migrated: {user.username} '
                                f'(superuser={user.is_superuser}, staff={user.is_staff})'
                            )
                        )
                        migrated_count += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(f'✗ Failed to migrate: {user.username}')
                        )
                        failed_count += 1
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Error migrating {user.username}: {str(e)}')
                )
                failed_count += 1
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'\n[DRY RUN] Would migrate {users.count()} user(s).'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nMigration complete: {migrated_count} succeeded, {failed_count} failed.'
                )
            )
            
            if migrated_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        '\n✓ Admin users have been migrated to D1 database. '
                        'You can now use the D1 admin_users table for authentication.'
                    )
                )

