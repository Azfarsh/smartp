from django.apps import AppConfig


class PrintConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'print'
    
    def ready(self):
        """
        Initialize background tasks when Django app is ready.
        This method is called once when Django starts.
        Note: ready() may be called multiple times during migrations, so we check if we're in a migration.
        """
        # Only start background tasks if not running migrations
        import sys
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        
        # Import here to avoid circular imports and ensure Django is fully initialized
        try:
            from print.views import start_traffic_updater
            start_traffic_updater()
        except Exception as e:
            # Log error but don't crash the app if traffic updater fails to start
            print(f"⚠️ Warning: Could not start traffic updater: {str(e)}")