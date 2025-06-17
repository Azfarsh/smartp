
#!/usr/bin/env python3
"""
Startup script for the complete Smart Print system
"""

import os
import sys
import time
import subprocess
import threading

def run_django_server():
    """Run Django development server"""
    print("🚀 Starting Django server...")
    os.chdir('/home/runner/workspace/smartprint')
    subprocess.run([sys.executable, 'manage.py', 'migrate'])
    subprocess.run([sys.executable, 'manage.py', 'runserver', '0.0.0.0:5000'])

def run_vendor_client():
    """Run vendor client after a delay"""
    print("⏰ Waiting 10 seconds for Django server to start...")
    time.sleep(10)
    print("🖨️  Starting vendor client...")
    os.chdir('/home/runner/workspace/smartprint')
    subprocess.run([sys.executable, 'vendor_client.py', '--vendor-id', 'vendor1', '--url', 'ws://0.0.0.0:5000', '--debug'])

def main():
    print("🎯 Starting Smart Print System...")
    
    # Start Django server in background thread
    django_thread = threading.Thread(target=run_django_server, daemon=True)
    django_thread.start()
    
    # Start vendor client in main thread
    run_vendor_client()

if __name__ == "__main__":
    main()
