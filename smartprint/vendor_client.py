#!/usr/bin/env python3
"""
Automated Vendor Print Client Script
====================================
Continuously monitors for print jobs via WebSocket and handles automatic printing
with linked list queue system and multiple printer support.
"""

import os
import sys
import time
import json
import argparse
import requests
import io
import platform
import websocket
import threading
import subprocess
import tempfile
import signal
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from dataclasses import dataclass
from collections import deque
import asyncio
from concurrent.futures import ThreadPoolExecutor
import win32print
import glob
from pathlib import Path
import logging
from queue import Queue
import psutil

# Additional imports for Windows printing
try:
    from PIL import Image, ImageDraw, ImageFont, ImageWin
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Platform-specific printer imports
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
        import win32ui
        import win32con
        PLATFORM_PRINTING = "windows"
    except ImportError:
        print("⚠️  Warning: win32print not available. Install pywin32 for Windows printing support.")
        PLATFORM_PRINTING = None
else:
    try:
        import cups
        PLATFORM_PRINTING = "cups"
    except ImportError:
        print("⚠️  Warning: pycups not available. Install pycups for Linux/Mac printing support.")
        PLATFORM_PRINTING = None

import math

# --- CONFIGURATION FOR LOCAL TESTING ---
API_URL = os.environ.get('VENDOR_API_URL', 'http://localhost:8000/auto-print-documents/')
API_TOKEN = os.environ.get('VENDOR_API_TOKEN', 'testtoken')  # Set your token here or via env
LOCAL_JOB_DIR = r'C:\Users\Azfar\Downloads\printjobs'
FAILED_JOB_DIR = os.path.join(LOCAL_JOB_DIR, 'failed_jobs')
POLL_INTERVAL = 10  # seconds
LONG_POLL_TIMEOUT = 30  # seconds
PRINTER_NAME = 'HP Deskjet 1510 series'  # or None for default

# Logging setup
activity_log_path = os.path.join(LOCAL_JOB_DIR, 'activity.log')
error_log_path = os.path.join(LOCAL_JOB_DIR, 'error.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.FileHandler(activity_log_path), logging.StreamHandler()])
error_logger = logging.getLogger('error')
fh = logging.FileHandler(error_log_path)
fh.setLevel(logging.ERROR)
error_logger.addHandler(fh)

@dataclass
class PrintJobNode:
    """Node for the linked list queue containing print job data"""
    filename: str
    download_url: str
    metadata: Dict
    service_type: str = "unknown"
    status: str = "pending"  # pending, processing, completed, failed
    attempts: int = 0
    max_attempts: int = 3
    created_time: float = None
    assigned_printer: str = None
    next_node: 'PrintJobNode' = None

    def __post_init__(self):
        if self.created_time is None:
            self.created_time = time.time()

class PrintJobQueue:
    """Linked list implementation for print job queue"""

    def __init__(self):
        self.head = None
        self.tail = None
        self.size = 0
        self.lock = threading.RLock()

    def enqueue(self, job_node: PrintJobNode):
        """Add a job to the end of the queue"""
        with self.lock:
            if self.tail is None:
                self.head = self.tail = job_node
            else:
                self.tail.next_node = job_node
                self.tail = job_node
            self.size += 1

    def dequeue(self) -> Optional[PrintJobNode]:
        """Remove and return the first job from the queue"""
        with self.lock:
            if self.head is None:
                return None

            job_node = self.head
            self.head = self.head.next_node

            if self.head is None:
                self.tail = None

            job_node.next_node = None
            self.size -= 1
            return job_node

    def peek(self) -> Optional[PrintJobNode]:
        """Return the first job without removing it"""
        with self.lock:
            return self.head

    def remove_by_filename(self, filename: str) -> bool:
        """Remove a specific job by filename"""
        with self.lock:
            if self.head is None:
                return False

            # If head node matches
            if self.head.filename == filename:
                self.head = self.head.next_node
                if self.head is None:
                    self.tail = None
                self.size -= 1
                return True

            # Search for the node
            current = self.head
            while current.next_node:
                if current.next_node.filename == filename:
                    current.next_node = current.next_node.next_node
                    if current.next_node is None:
                        self.tail = current
                    self.size -= 1
                    return True
                current = current.next_node

            return False

    def get_all_jobs(self) -> List[PrintJobNode]:
        """Get all jobs in the queue"""
        with self.lock:
            jobs = []
            current = self.head
            while current:
                jobs.append(current)
                current = current.next_node
            return jobs

    def is_empty(self) -> bool:
        """Check if queue is empty"""
        return self.size == 0

    def get_size(self) -> int:
        """Get queue size"""
        return self.size

class PrinterManager:
    """Manages multiple printers and job distribution"""

    def __init__(self, primary_printer: str = None, max_printers: int = 10):
        self.max_printers = max_printers
        self.printers = {}  # printer_name -> printer_info
        self.printer_status = {}  # printer_name -> status (idle, busy, error)
        self.printer_jobs = {}  # printer_name -> current_job
        self.lock = threading.RLock()
        self.primary_printer = primary_printer or "HP Deskjet 1510 series (copy 3)"

        # Initialize with primary printer
        self.add_printer(self.primary_printer)
        print(f"🖨️ Primary printer set: {self.primary_printer}")

    def add_printer(self, printer_name: str):
        """Add a printer to the manager"""
        with self.lock:
            if len(self.printers) >= self.max_printers:
                return False

            self.printers[printer_name] = {
                'name': printer_name,
                'added_time': time.time(),
                'jobs_completed': 0,
                'jobs_failed': 0
            }
            self.printer_status[printer_name] = 'idle'
            self.printer_jobs[printer_name] = None
            return True

    def get_available_printer(self) -> Optional[str]:
        # Always dynamically find a working printer
        fallback = find_working_printer()
        if fallback:
            if fallback not in self.printers:
                self.add_printer(fallback)
            return fallback
        return None

    def set_printer_busy(self, printer_name: str, job: PrintJobNode):
        """Mark printer as busy with a job"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'busy'
                self.printer_jobs[printer_name] = job

    def set_printer_idle(self, printer_name: str):
        """Mark printer as idle"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'idle'
                self.printer_jobs[printer_name] = None

    def set_printer_error(self, printer_name: str):
        """Mark printer as having an error"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'error'
                self.printer_jobs[printer_name] = None

    def get_printer_stats(self) -> Dict:
        """Get statistics for all printers"""
        with self.lock:
            stats = {
                'total_printers': len(self.printers),
                'idle_printers': len([s for s in self.printer_status.values() if s == 'idle']),
                'busy_printers': len([s for s in self.printer_status.values() if s == 'busy']),
                'error_printers': len([s for s in self.printer_status.values() if s == 'error']),
                'printers': []
            }

            for name, info in self.printers.items():
                stats['printers'].append({
                    'name': name,
                    'status': self.printer_status.get(name, 'unknown'),
                    'current_job': self.printer_jobs.get(name),
                    'jobs_completed': info.get('jobs_completed', 0),
                    'jobs_failed': info.get('jobs_failed', 0)
                })

            return stats

    def increment_job_completed(self, printer_name: str):
        """Increment completed job count for printer"""
        with self.lock:
            if printer_name in self.printers:
                self.printers[printer_name]['jobs_completed'] += 1

    def increment_job_failed(self, printer_name: str):
        """Increment failed job count for printer"""
        with self.lock:
            if printer_name in self.printers:
                self.printers[printer_name]['jobs_failed'] += 1

def find_working_printer():
    """Find a working printer, prioritizing HP printers."""
    import win32print
    
    try:
        # Get all printers
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        print(f"🔍 Found {len(printers)} printers on system")
        
        # List all printers for debugging
        for i, printer in enumerate(printers):
            print(f"   {i+1}. {printer[2]}")
        
        # First, try to get default printer
        try:
            default_printer = win32print.GetDefaultPrinter()
            print(f"🎯 Default printer: {default_printer}")
            
            # Check if default printer is working
            try:
                handle = win32print.OpenPrinter(default_printer)
                info = win32print.GetPrinter(handle, 2)
                win32print.ClosePrinter(handle)
                if info['Status'] == 0:
                    print(f"✅ Default printer is working: {default_printer}")
                    return default_printer
                else:
                    print(f"⚠️ Default printer has status {info['Status']}: {default_printer}")
            except Exception as e:
                print(f"❌ Default printer error: {e}")
        except Exception as e:
            print(f"❌ Could not get default printer: {e}")
        
        # Look for HP printers specifically
        hp_printers = [p[2] for p in printers if 'HP' in p[2].upper()]
        hp_printers.sort(key=lambda x: ('Copy' in x, x))  # Sort copy printers last
        
        print(f"🖨️ Found {len(hp_printers)} HP printers")
        for hp_printer in hp_printers:
            print(f"   🔍 Testing HP printer: {hp_printer}")
            try:
                handle = win32print.OpenPrinter(hp_printer)
                info = win32print.GetPrinter(handle, 2)
                win32print.ClosePrinter(handle)
                if info['Status'] == 0:
                    print(f"✅ Found working HP printer: {hp_printer}")
                    return hp_printer
                else:
                    print(f"⚠️ HP printer has status {info['Status']}: {hp_printer}")
            except Exception as e:
                print(f"❌ HP printer error: {e}")
                continue
        
        # Try any other non-PDF printer
        print("🔄 Trying other non-PDF printers...")
        for p in printers:
            printer_name = p[2]
            if 'PDF' not in printer_name.upper() and 'MICROSOFT' not in printer_name.upper():
                print(f"   🔍 Testing printer: {printer_name}")
                try:
                    handle = win32print.OpenPrinter(printer_name)
                    info = win32print.GetPrinter(handle, 2)
                    win32print.ClosePrinter(handle)
                    if info['Status'] == 0:
                        print(f"✅ Found working printer: {printer_name}")
                        return printer_name
                    else:
                        print(f"⚠️ Printer has status {info['Status']}: {printer_name}")
                except Exception as e:
                    print(f"❌ Printer error: {e}")
                    continue
        
        print("❌ No working printer found!")
        return None
        
    except Exception as e:
        print(f"❌ Error finding printers: {e}")
        return None

def create_passport_photo_layout(input_image_path, output_path, total_prints=8):
    """
    Create a passport photo layout with a dynamic grid (2x4, 4x4, 5x6) on a single A4 page.
    Args:
        input_image_path (str): Path to the input image
        output_path (str): Path to save the output layout
        total_prints (int): Number of passport photos (8, 16, 30)
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        print("📸 Creating passport photo layout...")
        PASSPORT_WIDTH = 413   # 35mm at 300 DPI
        PASSPORT_HEIGHT = 531  # 45mm at 300 DPI
        A4_WIDTH = 2480   # 210mm at 300 DPI
        A4_HEIGHT = 3508  # 297mm at 300 DPI
        MARGIN = 118      # 10mm margins
        SPACING = 59      # 5mm spacing between photos
        # Determine grid
        if total_prints == 8:
            cols, rows = 2, 4
        elif total_prints == 16:
            cols, rows = 4, 4
        elif total_prints == 30:
            cols, rows = 5, 6
        else:
            print(f"❌ Unsupported total_prints: {total_prints}")
            return False
        # Load and process the input image
        print(f"📂 Loading image: {input_image_path}")
        original_image = Image.open(input_image_path)
        if original_image.mode != 'RGB':
            original_image = original_image.convert('RGB')
        # Resize to passport photo dimensions while maintaining aspect ratio
        print("🔄 Resizing to passport photo dimensions...")
        original_width, original_height = original_image.size
        scale_width = PASSPORT_WIDTH / original_width
        scale_height = PASSPORT_HEIGHT / original_height
        scale = min(scale_width, scale_height)
        new_width = int(original_width * scale)
        new_height = int(original_height * scale)
        resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        passport_photo = Image.new('RGB', (PASSPORT_WIDTH, PASSPORT_HEIGHT), 'white')
        x_offset = (PASSPORT_WIDTH - new_width) // 2
        y_offset = (PASSPORT_HEIGHT - new_height) // 2
        passport_photo.paste(resized_image, (x_offset, y_offset))
        # Create the A4 layout
        print(f"📄 Creating A4 layout with {total_prints} passport photos...")
        layout = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), 'white')
        total_width = cols * PASSPORT_WIDTH + (cols - 1) * SPACING
        total_height = rows * PASSPORT_HEIGHT + (rows - 1) * SPACING
        start_x = (A4_WIDTH - total_width) // 2
        start_y = (A4_HEIGHT - total_height) // 2
        photo_count = 0
        for row in range(rows):
            for col in range(cols):
                if photo_count >= total_prints:
                    break
                x = start_x + col * (PASSPORT_WIDTH + SPACING)
                y = start_y + row * (PASSPORT_HEIGHT + SPACING)
                layout.paste(passport_photo, (x, y))
                photo_count += 1
        # Add corner marks for cutting guidance
        draw = ImageDraw.Draw(layout)
        mark_length = 20
        mark_color = 'black'
        for row in range(rows):
            for col in range(cols):
                if (row * cols + col) >= total_prints:
                    break
                x = start_x + col * (PASSPORT_WIDTH + SPACING)
                y = start_y + row * (PASSPORT_HEIGHT + SPACING)
                # Top-left
                draw.line([(x-5, y-5), (x-5+mark_length, y-5)], fill=mark_color, width=1)
                draw.line([(x-5, y-5), (x-5, y-5+mark_length)], fill=mark_color, width=1)
                # Top-right
                draw.line([(x+PASSPORT_WIDTH+5-mark_length, y-5), (x+PASSPORT_WIDTH+5, y-5)], fill=mark_color, width=1)
                draw.line([(x+PASSPORT_WIDTH+5, y-5), (x+PASSPORT_WIDTH+5, y-5+mark_length)], fill=mark_color, width=1)
                # Bottom-left
                draw.line([(x-5, y+PASSPORT_HEIGHT+5-mark_length), (x-5, y+PASSPORT_HEIGHT+5)], fill=mark_color, width=1)
                draw.line([(x-5, y+PASSPORT_HEIGHT+5), (x-5+mark_length, y+PASSPORT_HEIGHT+5)], fill=mark_color, width=1)
                # Bottom-right
                draw.line([(x+PASSPORT_WIDTH+5, y+PASSPORT_HEIGHT+5-mark_length), (x+PASSPORT_WIDTH+5, y+PASSPORT_HEIGHT+5)], fill=mark_color, width=1)
                draw.line([(x+PASSPORT_WIDTH+5-mark_length, y+PASSPORT_HEIGHT+5), (x+PASSPORT_WIDTH+5, y+PASSPORT_HEIGHT+5)], fill=mark_color, width=1)
        print(f"💾 Saving passport photo layout...")
        layout.save(output_path, 'JPEG', quality=95, dpi=(300, 300))
        print(f"✅ Passport photo layout created successfully!")
        print(f"   📁 Output file: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Error creating passport photo layout: {e}")
        return False

def print_image_automatically(image_path, printer_name, job_filename=None):
    """
    Print an image automatically using multiple methods, with queue monitoring if job_filename is provided.
    """
    def do_print():
        try:
            print(f"🖨️ Printing to: {printer_name}")
            ps_script = f'''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing
try {{
    $image = [System.Drawing.Image]::FromFile("{image_path}")
    $printDoc = New-Object System.Drawing.Printing.PrintDocument
    $printDoc.PrinterSettings.PrinterName = "{printer_name}"
    $printDoc.DefaultPageSettings.Color = $true
    $printDoc.DefaultPageSettings.Landscape = $false
    $printDoc.PrinterSettings.DefaultPageSettings.Color = $true
    foreach ($paperSize in $printDoc.PrinterSettings.PaperSizes) {{
        if ($paperSize.PaperName -eq "A4") {{
            $printDoc.DefaultPageSettings.PaperSize = $paperSize
            break
        }}
    }}
    foreach ($resolution in $printDoc.PrinterSettings.PrinterResolutions) {{
        if ($resolution.Kind -eq [System.Drawing.Printing.PrinterResolutionKind]::High) {{
            $printDoc.DefaultPageSettings.PrinterResolution = $resolution
            break
        }}
    }}
    $printPage = {{
        param($sender, $e)
        try {{
            $margin = 50
            $printWidth = $e.PageBounds.Width - (2 * $margin)
            $printHeight = $e.PageBounds.Height - (2 * $margin)
            $imageAspect = $image.Width / $image.Height
            $pageAspect = $printWidth / $printHeight
            if ($imageAspect -gt $pageAspect) {{
                $destWidth = $printWidth
                $destHeight = $printWidth / $imageAspect
            }} else {{
                $destHeight = $printHeight
                $destWidth = $printHeight * $imageAspect
            }}
            $x = $margin + (($printWidth - $destWidth) / 2)
            $y = $margin + (($printHeight - $destHeight) / 2)
            $destRect = New-Object System.Drawing.Rectangle($x, $y, $destWidth, $destHeight)
            $e.Graphics.DrawImage($image, $destRect)
        }} catch {{ Write-Host "Error in print page: $_" }}
    }}
    $printDoc.add_PrintPage($printPage)
    $printDoc.Print()
    $image.Dispose()
    Write-Host "Print job sent successfully"
    exit 0
}} catch {{ Write-Host "PowerShell printing error: $_"; exit 1 }}
'''
            result = subprocess.run(['powershell', '-Command', ps_script], 
                                  capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                print("   ✅ Print sent successfully using PowerShell")
                return True
            else:
                print(f"   ❌ PowerShell method failed: {result.stderr}")
            print("   📄 Method 2: Using Windows Photo Viewer...")
            try:
                cmd = [
                    'rundll32.exe',
                    'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
                    image_path,
                    printer_name
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print("   ✅ Print sent successfully using Windows Photo Viewer")
                    return True
            except Exception as e:
                print(f"   ❌ Windows Photo Viewer method failed: {e}")
            print("   📄 Method 3: Using default print action...")
            try:
                win32api.ShellExecute(0, "print", image_path, None, ".", 0)
                print("   ✅ Print sent using default print action")
                return True
            except Exception as e:
                print(f"   ❌ Default print action failed: {e}")
            return False
        except Exception as e:
            print(f"❌ Error in print_image_automatically: {e}")
            return False
    if job_filename:
        return wait_for_job_in_and_out_of_queue(printer_name, job_filename, do_print)
    else:
        return do_print()

def is_job_in_queue(printer_name, job_filename):
    """
    Check if a print job with the given filename is present in the printer queue.
    """
    try:
        handle = win32print.OpenPrinter(printer_name)
        jobs = win32print.EnumJobs(handle, 0, -1, 1)
        win32print.ClosePrinter(handle)
        for job in jobs:
            if job_filename in job['pDocument']:
                return True
        return False
    except Exception as e:
        print(f"Error checking print queue: {e}")
        return False

def wait_for_job_in_and_out_of_queue(printer_name, job_filename, print_func, max_retries=5):
    """
    Repeatedly send the print job until it appears in the queue.
    Then wait until it disappears (printed).
    """
    appeared = False
    retries = 0
    while retries < max_retries:
        print_func()
        time.sleep(2)
        for _ in range(15):
            if is_job_in_queue(printer_name, job_filename):
                appeared = True
                break
            time.sleep(2)
        if appeared:
            break
        retries += 1
    if not appeared:
        print(f"Job {job_filename} never appeared in queue after {max_retries} attempts.")
        return False
    for _ in range(60):
        if not is_job_in_queue(printer_name, job_filename):
            print(f"Job {job_filename} has been printed and removed from queue.")
            return True
        time.sleep(2)
    print(f"Job {job_filename} did not leave the queue in time.")
    return False

class AutomatedVendorPrintClient:
    def __init__(self, vendor_id: str, base_url: str = "ws://localhost:8000", debug: bool = False, primary_printer: str = None):
        """
        Initialize the automated vendor print client with enhanced queue system.

        Args:
            vendor_id: Vendor ID for identification
            base_url: Base WebSocket URL of the Django application
            debug: Enable debug logging
            primary_printer: Primary printer name to use
        """
        self.vendor_id = vendor_id

        # Handle different URL formats
        if base_url.startswith('http://'):
            self.base_url = base_url.replace('http://', 'ws://')
        elif base_url.startswith('https://'):
            self.base_url = base_url.replace('https://', 'wss://')
        elif not base_url.startswith(('ws://', 'wss://')):
            self.base_url = f"ws://{base_url}"
        else:
            self.base_url = base_url

        # Remove trailing slash if present
        self.base_url = self.base_url.rstrip('/')

        self.debug = debug
        self.ws = None
        self.is_running = True

        # Enhanced queue system
        self.print_queue = PrintJobQueue()
        self.processed_jobs = set()  # Cache of completed job filenames
        self.failed_jobs_queue = PrintJobQueue()  # Priority queue for failed jobs

        # Printer management
        self.printer_manager = PrinterManager(primary_printer=primary_printer)

        # Threading and processing
        self.executor = ThreadPoolExecutor(max_workers=10)  # For parallel processing
        self.processing_threads = {}  # Track active processing threads
        self.queue_processor_running = False

        # Performance tracking
        self.job_metrics = {
            'total_received': 0,
            'total_completed': 0,
            'total_failed': 0,
            'average_processing_time': 0,
            'processing_times': deque(maxlen=100)  # Keep last 100 processing times
        }

        self.log("🚀 Enhanced Automated Vendor Print Client initialized")
        if self.debug:
            self.log(f"📍 Base URL: {self.base_url}")
            self.log(f"🔑 Using Vendor ID: {self.vendor_id}")
            self.log("📊 Enhanced queue system with printer management enabled")

        self.job_dir = r"C:\Users\Azfar\Downloads\printjobs"
        self.job_scan_interval = 10  # seconds
        self.seen_tokens = set()
        # Set vendor-specific folder path
        self.vendor_folder_path = f'vendor_register_details/{self.vendor_id}/firozshop'

        # API endpoint for getting vendor jobs
        self.vendor_api_url = f"{base_url.replace('ws://', 'http://').replace('wss://', 'https://')}/get-vendor-print-jobs/"
        
        # For Replit, ensure we use the correct port
        if 'localhost' in self.vendor_api_url:
            self.vendor_api_url = self.vendor_api_url.replace('localhost:8000', '0.0.0.0:8000')
        if '127.0.0.1' in self.vendor_api_url:
            self.vendor_api_url = self.vendor_api_url.replace('127.0.0.1:8000', '0.0.0.0:8000')

        threading.Thread(target=self.job_directory_watcher, daemon=True).start()
        threading.Thread(target=self.vendor_api_poller, daemon=True).start()

    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")

    def debug_log(self, message: str):
        """Log debug messages only if debug mode is enabled."""
        if self.debug:
            self.log(message, "DEBUG")

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages with enhanced processing."""
        try:
            data = json.loads(message)
            message_type = data.get('type')

            if message_type == 'print_job':
                job = data.get('job')
                if job and job.get('metadata', {}).get('status') == 'no':
                    self.handle_new_print_job(job)

            elif message_type == 'print_jobs_response':
                jobs = data.get('jobs', [])
                if jobs:
                    # Filter jobs with status 'no'
                    pending_jobs = [job for job in jobs if job.get('metadata', {}).get('status') == 'no']
                    if pending_jobs:
                        self.handle_multiple_print_jobs(pending_jobs)
                    else:
                        self.debug_log("📭 No jobs with status 'no' found")
                else:
                    self.debug_log("📭 No print jobs available")

            elif message_type == 'job_status_updated':
                filename = data.get('filename', 'unknown')
                status = data.get('status', 'unknown')
                self.log(f"✅ Job status updated: {filename} -> {status}")

            elif message_type == 'error':
                self.log(f"❌ Server error: {data.get('message', 'Unknown error')}")

        except json.JSONDecodeError:
            self.log("❌ Invalid JSON message received")
        except Exception as e:
            self.log(f"❌ Error processing message: {str(e)}")

    def handle_new_print_job(self, job):
        """Handle a new print job by adding it to the queue"""
        filename = job.get('filename', 'unknown')

        # Check if already processed
        if filename in self.processed_jobs:
            self.debug_log(f"🔄 Skipping already processed job: {filename}")
            return

        # Create job node
        job_node = PrintJobNode(
            filename=filename,
            download_url=job.get('download_url', ''),
            metadata=job.get('metadata', {}),
            service_type=job.get('service_type', 'unknown')
        )

        # Add to queue
        self.print_queue.enqueue(job_node)
        self.job_metrics['total_received'] += 1

        self.log(f"📋 Added print job to queue: {filename} (Queue size: {self.print_queue.get_size()})")

        # Start queue processor if not running
        if not self.queue_processor_running:
            threading.Thread(target=self.process_print_queue, daemon=True).start()

    def handle_multiple_print_jobs(self, jobs):
        """Handle multiple print jobs efficiently"""
        new_jobs = []

        for job in jobs:
            filename = job.get('filename', 'unknown')

            if filename not in self.processed_jobs:
                job_node = PrintJobNode(
                    filename=filename,
                    download_url=job.get('download_url', ''),
                    metadata=job.get('metadata', {}),
                    service_type=job.get('service_type', 'unknown')
                )
                new_jobs.append(job_node)
                self.processed_jobs.add(filename)

        if new_jobs:
            # Add all jobs to queue
            for job_node in new_jobs:
                self.print_queue.enqueue(job_node)
                self.job_metrics['total_received'] += 1

            self.log(f"📋 Added {len(new_jobs)} print jobs to queue (Queue size: {self.print_queue.get_size()})")

            # Start queue processor if not running
            if not self.queue_processor_running:
                threading.Thread(target=self.process_print_queue, daemon=True).start()
        else:
            self.debug_log("📭 No new print jobs to process")

    def process_print_queue(self):
        """Main queue processor with strict sequential printing (single-threaded)"""
        self.queue_processor_running = True
        self.log("🔄 Starting SEQUENTIAL print queue processor")

        try:
            while self.is_running and (not self.print_queue.is_empty() or not self.failed_jobs_queue.is_empty()):
                job_node = None
                
                # Process failed jobs first (priority)
                if not self.failed_jobs_queue.is_empty():
                    job_node = self.failed_jobs_queue.dequeue()
                    if job_node:
                        self.log(f"🔄 Processing priority failed job: {job_node.filename}")
                
                # Process regular jobs
                elif not self.print_queue.is_empty():
                    job_node = self.print_queue.dequeue()
                    if job_node:
                        self.log(f"🔄 Processing job: {job_node.filename}")

                if job_node:
                    # Process job SYNCHRONOUSLY (single-threaded)
                    success = self.process_single_job_sequential(job_node)
                    self.handle_job_completion(job_node, success)
                    
                    # STRICT DELAY between jobs (30-60 seconds)
                    if self.is_running:
                        delay_time = 45  # 45 seconds between jobs
                        self.log(f"⏰ Waiting {delay_time} seconds before next job...")
                        time.sleep(delay_time)

                # Small delay if no jobs to process
                else:
                    time.sleep(5)

        except Exception as e:
            self.log(f"❌ Error in sequential queue processor: {str(e)}")
        finally:
            self.queue_processor_running = False
            self.log("⏹️ Sequential print queue processor stopped")

    def process_single_job_sequential(self, job_node: PrintJobNode) -> bool:
        """Process a single job sequentially (synchronous) with strict controls"""
        start_time = time.time()
        
        try:
            # Always get a working printer dynamically
            printer_name = self.printer_manager.get_available_printer()
            if not printer_name:
                self.log(f"❌ No available printer for job: {job_node.filename}")
                return False

            # Find the token (json file) for this job
            token = None
            for file in glob.glob(os.path.join(self.job_dir, 'vendor_jobs', '*.json')):
                if job_node.filename in file or Path(file).stem == job_node.filename.split('.')[0]:
                    token = Path(file).stem
                    break

            self.log(f"🖨️ SEQUENTIAL Processing: {job_node.filename} (token: {token}) on {printer_name}")
            
            # Set job status
            job_node.status = "processing"
            job_node.assigned_printer = printer_name
            job_node.attempts += 1

            # Download document
            document_path = os.path.join(self.job_dir, 'vendor_jobs', job_node.filename)
            try:
                response = requests.get(job_node.download_url, stream=True, timeout=30)
                response.raise_for_status()
                with open(document_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                self.log(f"✅ Downloaded document to {document_path}")
            except Exception as e:
                self.log(f"❌ Failed to download document: {e}")
                return False

            # Prepare print settings
            print_settings = self.prepare_print_settings(job_node.metadata)
            
            # Print the document SEQUENTIALLY
            print_success = self.print_document_sequential(
                document_path, printer_name, job_node.filename, print_settings
            )

            # Clean up downloaded file
            try:
                os.remove(document_path)
            except Exception:
                pass

            if print_success:
                processing_time = time.time() - start_time
                self.log(f"✅ Successfully completed job: {job_node.filename} ({processing_time:.2f}s)")
                
                # Delete the JSON file after successful print
                if token:
                    json_file = os.path.join(self.job_dir, 'vendor_jobs', f'{token}.json')
                    try:
                        os.remove(json_file)
                        self.log(f"🗑️ Deleted job file: {json_file}")
                        self.seen_tokens.discard(token)
                    except Exception as e:
                        self.log(f"❌ Failed to delete job file {json_file}: {e}")
                
                return True
            else:
                self.log(f"❌ Printing failed for job: {job_node.filename}")
                return False

        except Exception as e:
            self.log(f"❌ Error in sequential job processing: {e}")
            return False

    def process_single_job_async(self, job_node: PrintJobNode, priority: bool = False):
        try:
            # Always get a working printer dynamically
            printer_name = self.printer_manager.get_available_printer()

            if not printer_name:
                # No available printer, re-queue the job
                if priority:
                    self.failed_jobs_queue.enqueue(job_node)
                else:
                    self.print_queue.enqueue(job_node)
                self.debug_log(f"⏳ No available printer, re-queuing job: {job_node.filename}")
                time.sleep(2)  # Wait before retry
                return

            # Assign printer and mark as busy
            job_node.assigned_printer = printer_name
            job_node.status = "processing"
            self.printer_manager.set_printer_busy(printer_name, job_node)

            # Submit job to thread pool
            future = self.executor.submit(self.process_job_with_printer, job_node, printer_name)
            self.processing_threads[job_node.filename] = future

            # Handle completion
            def on_job_complete(fut):
                try:
                    success = fut.result()
                    self.handle_job_completion(job_node, success, priority)
                except Exception as e:
                    self.log(f"❌ Error in job processing thread: {str(e)}")
                    self.handle_job_completion(job_node, False, priority)
                finally:
                    # Clean up
                    self.processing_threads.pop(job_node.filename, None)
                    self.printer_manager.set_printer_idle(printer_name)

            future.add_done_callback(on_job_complete)

        except Exception as e:
            self.log(f"❌ Error processing job async: {str(e)}")
            self.handle_job_completion(job_node, False, priority)

    def process_job_with_printer(self, job_node: PrintJobNode, printer_name: str) -> bool:
        """Process a print job with assigned printer including interrupt handling"""
        start_time = time.time()
        checkpoint_file = None
        token = None
        try:
            # Find the token (json file) for this job
            for file in glob.glob(os.path.join(self.job_dir, 'vendor_jobs', '*.json')):
                if job_node.filename in file or Path(file).stem == job_node.filename.split('.')[0]:
                    token = Path(file).stem
                    break
            self.log(f"🖨️ Processing {job_node.filename} (token: {token}) on {printer_name} (Attempt {job_node.attempts + 1})")
            if not printer_name:
                self.log(f"❌ No printer found for job: {job_node.filename}")
                return False
            # Download document to job_dir with correct filename
            document_path = os.path.join(self.job_dir, 'vendor_jobs', job_node.filename)
            try:
                response = requests.get(job_node.download_url, stream=True, timeout=30)
                response.raise_for_status()
                with open(document_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                self.log(f"✅ Downloaded document to {document_path}")
            except Exception as e:
                self.log(f"❌ Failed to download document: {e}")
                return False
            # Print the document
            print_settings = self.prepare_print_settings(job_node.metadata)
            print_success = self.print_document_with_settings(
                open(document_path, 'rb').read(), printer_name, job_node.filename, print_settings
            )
            # Clean up downloaded file
            try:
                os.remove(document_path)
            except Exception:
                pass
            if print_success:
                processing_time = time.time() - start_time
                self.log(f"✅ Successfully completed job: {job_node.filename} ({processing_time:.2f}s)")
                # Delete the JSON file after successful print
                if token:
                    json_file = os.path.join(self.job_dir, 'vendor_jobs', f'{token}.json')
                    try:
                        os.remove(json_file)
                        self.log(f"🗑️ Deleted job file: {json_file}")
                        self.seen_tokens.discard(token)
                    except Exception as e:
                        self.log(f"❌ Failed to delete job file {json_file}: {e}")
                return True
            else:
                self.log(f"❌ Printing failed for job: {job_node.filename}")
                return False
        except Exception as e:
            self.log(f"❌ Error processing job: {e}")
            return False

    def _print_with_interrupt_handling(self, document_data: bytes, printer_name: str, 
                                     filename: str, print_settings: Dict, job_node: PrintJobNode) -> bool:
        """Print document with enhanced interrupt handling and auto-recovery"""
        try:
            copies = print_settings.get('copies', 1)
            completed_copies = getattr(job_node, 'completed_copies', 0)
            self.log(f"🖨️ Starting print job: {filename} (copies {completed_copies + 1}-{copies})")
            # Update print settings for remaining copies
            remaining_copies = copies - completed_copies
            if remaining_copies <= 0:
                self.log(f"✅ All copies already completed for {filename}")
                return True
            print_settings['copies'] = remaining_copies
            # Directly call the print logic (no signal handling in threads)
            success = self.print_document_with_settings(
                document_data, printer_name, filename, print_settings
            )
            if success:
                job_node.completed_copies = copies
                self.log(f"✅ All {copies} copies completed for {filename}")
                return True
            else:
                return False
        except Exception as e:
            self.log(f"❌ Error in interrupt-aware printing: {e}")
            return False

    def _create_job_checkpoint(self, job_node: PrintJobNode, printer_name: str) -> str:
        """Create checkpoint file for job recovery"""
        try:
            checkpoint_dir = tempfile.gettempdir()
            checkpoint_file = os.path.join(checkpoint_dir, f"printjob_{job_node.filename}.checkpoint")

            checkpoint_data = {
                'filename': job_node.filename,
                'printer_name': printer_name,
                'attempts': job_node.attempts,
                'created_time': job_node.created_time,
                'completed_copies': getattr(job_node, 'completed_copies', 0),
                'metadata': job_node.metadata
            }

            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f)

            return checkpoint_file

        except Exception as e:
            self.debug_log(f"Error creating checkpoint: {e}")
            return None

    def _save_job_checkpoint(self, job_node: PrintJobNode, printer_name: str, 
                           document_data: bytes, print_settings: Dict):
        """Save job checkpoint with document data"""
        try:
            checkpoint_dir = tempfile.gettempdir()
            data_file = os.path.join(checkpoint_dir, f"printjob_{job_node.filename}.data")

            checkpoint_data = {
                'filename': job_node.filename,
                'printer_name': printer_name,
                'attempts': job_node.attempts,
                'completed_copies': getattr(job_node, 'completed_copies', 0),
                'print_settings': print_settings,
                'metadata': job_node.metadata,
                'save_time': time.time()
            }

            # Save document data separately
            with open(data_file, 'wb') as f:
                f.write(document_data)

            # Save checkpoint metadata
            checkpoint_file = os.path.join(checkpoint_dir, f"printjob_{job_node.filename}.checkpoint")
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f)

        except Exception as e:
            self.debug_log(f"Error saving checkpoint: {e}")

    def _check_resume_checkpoint(self, filename: str) -> Optional[Dict]:
        """Check if job can be resumed from checkpoint"""
        try:
            checkpoint_dir = tempfile.gettempdir()
            checkpoint_file = os.path.join(checkpoint_dir, f"printjob_{filename}.checkpoint")
            data_file = os.path.join(checkpoint_dir, f"printjob_{filename}.data")

            if os.path.exists(checkpoint_file) and os.path.exists(data_file):
                # Check if checkpoint is recent (within 24 hours)
                if time.time() - os.path.getmtime(checkpoint_file) < 86400:
                    with open(checkpoint_file, 'r') as f:
                        checkpoint_data = json.load(f)

                    with open(data_file, 'rb') as f:
                        document_data = f.read()

                    return {
                        'document_data': document_data,
                        'print_settings': checkpoint_data.get('print_settings', {}),
                        'completed_copies': checkpoint_data.get('completed_copies', 0)
                    }

            return None

        except Exception as e:
            self.debug_log(f"Error checking resume checkpoint: {e}")
            return None

    def _cleanup_job_checkpoint(self, filename: str):
        """Clean up checkpoint files after successful completion"""
        try:
            checkpoint_dir = tempfile.gettempdir()
            checkpoint_file = os.path.join(checkpoint_dir, f"printjob_{filename}.checkpoint")
            data_file = os.path.join(checkpoint_dir, f"printjob_{filename}.data")

            for file_path in [checkpoint_file, data_file]:
                if os.path.exists(file_path):
                    os.remove(file_path)

            self.debug_log(f"🧹 Cleaned up checkpoint for {filename}")

        except Exception as e:
            self.debug_log(f"Error cleaning checkpoint: {e}")

    def _save_interrupt_checkpoint(self, job_node: PrintJobNode, printer_name: str):
        """Save checkpoint when interrupted"""
        try:
            self.log(f"💾 Saving interrupt checkpoint for {job_node.filename}")
            checkpoint_dir = tempfile.gettempdir()
            interrupt_file = os.path.join(checkpoint_dir, f"interrupted_{job_node.filename}.checkpoint")

            interrupt_data = {
                'filename': job_node.filename,
                'printer_name': printer_name,
                'interrupted_time': time.time(),
                'attempts': job_node.attempts,
                'completed_copies': getattr(job_node, 'completed_copies', 0),
                'metadata': job_node.metadata
            }

            with open(interrupt_file, 'w') as f:
                json.dump(interrupt_data, f)

        except Exception as e:
            self.debug_log(f"Error saving interrupt checkpoint: {e}")

    def handle_job_completion(self, job_node: PrintJobNode, success: bool, was_priority: bool = False):
        """Handle job completion or failure with retry logic"""
        if success:
            job_node.status = "completed"
            self.processed_jobs.add(job_node.filename)

            # Notify backend
            self.notify_job_completed(job_node.filename)
            self.update_r2_job_status(job_node.filename, 'YES')

        else:
            job_node.status = "failed"
            self.job_metrics['total_failed'] += 1

            # Retry logic
            if job_node.attempts < job_node.max_attempts:
                self.log(f"🔄 Retrying failed job: {job_node.filename} (Attempt {job_node.attempts + 1}/{job_node.max_attempts})")

                # Add to priority failed jobs queue for immediate retry
                self.failed_jobs_queue.enqueue(job_node)

                # If this was a priority job that failed, pause other processing briefly
                if was_priority:
                    time.sleep(1)

            else:
                self.log(f"❌ Job failed permanently: {job_node.filename} (Max attempts reached)")
                self.notify_job_failed(job_node.filename, f"Failed after {job_node.max_attempts} attempts")

                # Remove from processed cache to allow manual retry later
                self.processed_jobs.discard(job_node.filename)

    def prepare_print_settings(self, metadata):
        """Prepare print settings from metadata."""
        return {
            'copies': int(metadata.get('copies', 1)),
            'color': metadata.get('color', 'Black and White'),
            'orientation': metadata.get('orientation', 'portrait'),
            'page_size': metadata.get('page_size', 'A4'),
            'page_range': metadata.get('page_range', 'all'),
            'specific_pages': metadata.get('specific_pages', ''),
            'spiral_binding': metadata.get('spiral_binding', 'No'),
            'lamination': metadata.get('lamination', 'No'),
            'service_type': metadata.get('service_type', 'unknown')
        }

    def get_available_printers(self) -> List[str]:
        """Get list of available printers on the system."""
        printers = []

        try:
            if PLATFORM_PRINTING == "windows":
                # Windows printer detection
                printers_info = win32print.EnumPrinters(2)
                printers = [printer[2] for printer in printers_info]

            elif PLATFORM_PRINTING == "cups":
                # CUPS printer detection (Linux/Mac)
                conn = cups.Connection()
                printers_dict = conn.getPrinters()
                printers = list(printers_dict.keys())

        except Exception as e:
            self.debug_log(f"Error detecting printers: {str(e)}")

        return printers

    def is_printer_available(self) -> Tuple[bool, Optional[str]]:
        """Check if any printer is available."""
        printers = self.get_available_printers()

        if not printers:
            return False, None

        # Return the first available printer
        default_printer = printers[0]

        if PLATFORM_PRINTING == "windows":
            try:
                # Get default printer on Windows
                default_printer = win32print.GetDefaultPrinter()
            except:
                pass

        self.debug_log(f"🖨️  Available printers: {', '.join(printers)}")
        self.debug_log(f"🎯 Using printer: {default_printer}")

        return True, default_printer

    def is_specific_printer_available(self, printer_name: str) -> bool:
        """Check if a specific printer is available"""
        available_printers = self.get_available_printers()
        return printer_name in available_printers

    def download_document(self, file_url: str) -> Optional[bytes]:
        """Download document content from the signed URL."""
        try:
            self.debug_log(f"⬇️  Downloading document from: {file_url[:50]}...")

            # Use a separate session for document download
            response = requests.get(file_url, timeout=30, stream=True)

            if response.status_code == 200:
                # Read content into memory
                document_data = response.content
                self.debug_log(f"✅ Downloaded {len(document_data)} bytes")
                return document_data
            else:
                self.log(f"❌ Failed to download document: HTTP {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            self.log(f"❌ Error downloading document: {str(e)}")
            return None

    def print_document_sequential(self, file_path: str, printer_name: str, 
                                filename: str, print_settings: Dict) -> bool:
        """Print document sequentially with SumatraPDF priority and strict process management"""
        try:
            copies = print_settings.get('copies', 1)
            service_type = print_settings.get('service_type', 'unknown')
            
            self.log(f"🖨️ SEQUENTIAL Printing: {filename} ({copies} copies) to {printer_name}")
            self.log(f"📋 Settings: {print_settings}")
            
            # Handle passport photos
            if service_type == 'passport_photo':
                return self._handle_passport_photo_printing_sequential(file_path, printer_name, filename, print_settings)
            
            # Determine file type
            file_extension = filename.lower().split('.')[-1]
            
            # Validate printer availability
            if not printer_name or not self.is_specific_printer_available(printer_name):
                self.log(f"🔍 Printer '{printer_name}' not available, auto-selecting working printer...")
                printer_name = find_working_printer()
                if not printer_name:
                    self.log("❌ No working printer found!")
                    return False
                self.log(f"🎯 Using printer: {printer_name}")
            
            # Route to appropriate printing method
            if file_extension == 'pdf':
                return self._print_pdf_sequential(file_path, printer_name, copies, print_settings)
            elif file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
                return self._print_image_sequential(file_path, printer_name, copies)
            else:
                return self._print_generic_sequential(file_path, printer_name, copies)
                
        except Exception as e:
            self.log(f"❌ Sequential printing failed: {str(e)}")
            return False

    def print_document_with_settings(self, document_data: bytes, printer_name: str, 
                                   filename: str, print_settings: Dict) -> bool:
        """Print document with specific settings using secure printing and queue monitoring."""
        try:
            copies = print_settings.get('copies', 1)
            service_type = print_settings.get('service_type', 'unknown')
            self.log(f"🖨️  Printing {filename} ({copies} copies) to {printer_name}")
            self.log(f"📋 Settings: {print_settings}")
            if service_type == 'passport_photo':
                return self._handle_passport_photo_printing(document_data, printer_name, filename, print_settings)
            file_extension = filename.lower().split('.')[-1]
            temp_fd, temp_path = tempfile.mkstemp(suffix=f'.{file_extension}', prefix='secure_print_')
            try:
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(document_data)
                if not printer_name or not self.is_specific_printer_available(printer_name):
                    self.log(f"🔍 Printer '{printer_name}' not available, auto-selecting working printer...")
                    printer_name = find_working_printer()
                    if not printer_name:
                        self.log("❌ No working printer found!")
                        return False
                    self.log(f"🎯 Using printer: {printer_name}")
                if file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
                    return print_image_automatically(temp_path, printer_name, filename)
                elif file_extension == 'pdf':
                    def print_func():
                        self._secure_print_pdf(temp_path, printer_name, copies, print_settings.get('color', 'Black and White') == 'color')
                    return wait_for_job_in_and_out_of_queue(printer_name, filename, print_func)
                elif file_extension in ['doc', 'docx', 'txt', 'rtf']:
                    def print_func():
                        self._secure_print_document(temp_path, printer_name, copies)
                    return wait_for_job_in_and_out_of_queue(printer_name, filename, print_func)
                else:
                    def print_func():
                        self._secure_print_generic(temp_path, printer_name, copies)
                    return wait_for_job_in_and_out_of_queue(printer_name, filename, print_func)
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
        except Exception as e:
            self.log(f"❌ Printing failed: {str(e)}")
            return False

    def _handle_passport_photo_printing(self, document_data: bytes, printer_name: str, filename: str, print_settings: Dict) -> bool:
        """Handle passport photo printing by creating layout and printing."""
        try:
            self.log("📸 Processing passport photo service...")
            input_temp_fd, input_temp_path = tempfile.mkstemp(suffix='.jpg', prefix='passport_input_')
            output_temp_fd, output_temp_path = tempfile.mkstemp(suffix='.jpg', prefix='passport_layout_')
            try:
                with os.fdopen(input_temp_fd, 'wb') as input_file:
                    input_file.write(document_data)
                if not printer_name or not self.is_specific_printer_available(printer_name):
                    self.log(f"🔍 Printer '{printer_name}' not available, auto-selecting working printer...")
                    printer_name = find_working_printer()
                    if not printer_name:
                        self.log("❌ No working printer found!")
                        return False
                    self.log(f"🎯 Using printer: {printer_name}")
                # Get number of photos for layout
                total_prints = print_settings.get('copies', 8)
                if total_prints not in (8, 16, 30):
                    self.log(f"❌ Unsupported number of passport photos: {total_prints}. Only 8, 16, or 30 allowed.")
                    return False
                self.log(f"🔄 Creating passport photo layout for {total_prints} photos...")
                layout_success = create_passport_photo_layout(input_temp_path, output_temp_path, total_prints=total_prints)
                if not layout_success:
                    self.log("❌ Failed to create passport photo layout")
                    return False
                self.log(f"🖨️ Printing passport photo layout (1 copy)...")
                success = print_image_automatically(output_temp_path, printer_name)
                if success:
                    self.log("✅ Passport photos printed successfully!")
                    self.log(f"📄 {total_prints} passport-size photos (35x45mm each) on one A4 page")
                    self.log("✂️ Cut along the corner marks for individual photos")
                    self.log("🎨 Printed in high quality with color settings")
                return success
            finally:
                for temp_path in [input_temp_path, output_temp_path]:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
        except Exception as e:
            self.log(f"❌ Passport photo printing error: {str(e)}")
            return False

    def _print_pdf_sequential(self, file_path: str, printer_name: str, copies: int, print_settings: Dict) -> bool:
        """Sequential PDF printing with SumatraPDF priority and strict process management"""
        try:
            self.log(f"🔍 Starting SEQUENTIAL PDF printing ({copies} copies)")
            
            # PRIORITIZE SumatraPDF over Adobe Reader
            if self._try_sumatra_sequential(file_path, printer_name, copies):
                self.log("✅ PDF printed using SumatraPDF (PREFERRED)")
                return True
            
            # Fallback to Adobe Reader with strict process management
            self.log("🔄 SumatraPDF failed, trying Adobe Reader with strict controls...")
            if self._try_adobe_sequential(file_path, printer_name, copies):
                self.log("✅ PDF printed using Adobe Reader")
                return True
            
            # Final fallback to Windows CMD methods
            self.log("🔄 Adobe failed, trying Windows CMD methods...")
            if self._try_windows_pdf_sequential(file_path, printer_name, copies):
                self.log("✅ PDF printed using Windows CMD")
                return True
            
            self.log("❌ All PDF printing methods failed")
            return False
            
        except Exception as e:
            self.log(f"❌ Sequential PDF print error: {str(e)}")
            return False

    def _try_sumatra_sequential(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Try printing with SumatraPDF - PREFERRED METHOD"""
        try:
            self.log("🔍 Trying SumatraPDF (PRIORITY METHOD)...")
            
            # Find SumatraPDF installation
            sumatra_paths = [
                r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
                r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
                r"C:\Users\Public\SumatraPDF\SumatraPDF.exe"
            ]
            
            sumatra_exe = None
            for path in sumatra_paths:
                if os.path.exists(path):
                    sumatra_exe = path
                    self.log(f"✅ Found SumatraPDF at: {path}")
                    break
            
            if not sumatra_exe:
                self.log("❌ SumatraPDF not found")
                return False
            
            # Print each copy with queue monitoring
            success_count = 0
            for copy_num in range(copies):
                self.log(f"🖨️ SumatraPDF printing copy {copy_num + 1}/{copies}")
                
                try:
                    # Create unique job name for queue monitoring
                    job_name = f"Sumatra_{os.path.basename(file_path)}_{copy_num + 1}_{int(time.time())}"
                    
                    # Execute SumatraPDF command
                    cmd = [sumatra_exe, "-print-to", printer_name, "-silent", file_path]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    
                    if result.returncode == 0:
                        self.log(f"✅ SumatraPDF command successful for copy {copy_num + 1}")
                        
                        # Wait for job to appear and complete in queue
                        if self._monitor_print_queue_completion(printer_name, os.path.basename(file_path), timeout=120):
                            success_count += 1
                            self.log(f"✅ Copy {copy_num + 1} completed successfully")
                        else:
                            self.log(f"❌ Copy {copy_num + 1} failed queue monitoring")
                    else:
                        self.log(f"❌ SumatraPDF command failed for copy {copy_num + 1}: {result.stderr}")
                    
                    # Delay between copies
                    if copy_num < copies - 1:
                        time.sleep(10)
                        
                except Exception as e:
                    self.log(f"❌ Error with SumatraPDF copy {copy_num + 1}: {e}")
            
            # Consider successful if most copies printed
            if success_count >= max(1, copies // 2):
                self.log(f"✅ SumatraPDF successful: {success_count}/{copies} copies")
                return True
            else:
                self.log(f"❌ SumatraPDF insufficient success: {success_count}/{copies} copies")
                return False
                
        except Exception as e:
            self.log(f"❌ SumatraPDF error: {e}")
            return False

    def _try_adobe_sequential(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Try Adobe Reader with STRICT process management and cleanup"""
        try:
            self.log("🔍 Trying Adobe Reader with strict process management...")
            
            # Find Adobe Reader
            adobe_paths = [
                r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
                r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
                r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe"
            ]
            
            adobe_exe = None
            for path in adobe_paths:
                if os.path.exists(path):
                    adobe_exe = path
                    self.log(f"✅ Found Adobe Reader at: {path}")
                    break
            
            if not adobe_exe:
                self.log("❌ Adobe Reader not found")
                return False
            
            success_count = 0
            
            for copy_num in range(copies):
                self.log(f"🖨️ Adobe Reader printing copy {copy_num + 1}/{copies}")
                
                try:
                    # 1. TERMINATE any existing Adobe processes
                    self._terminate_adobe_processes()
                    time.sleep(2)
                    
                    # 2. Create unique temporary file to avoid conflicts
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix=f'adobe_print_{copy_num}_')
                    try:
                        # Copy file to unique temp location
                        with open(file_path, 'rb') as src, os.fdopen(temp_fd, 'wb') as dst:
                            dst.write(src.read())
                        
                        # 3. Execute Adobe command
                        cmd = [adobe_exe, "/t", temp_path, printer_name]
                        self.log(f"🔧 Adobe command: {' '.join(cmd)}")
                        
                        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        
                        # 4. Wait for process completion with timeout
                        try:
                            stdout, stderr = process.communicate(timeout=90)
                            
                            if process.returncode == 0:
                                self.log(f"✅ Adobe command successful for copy {copy_num + 1}")
                                
                                # 5. Monitor print queue
                                if self._monitor_print_queue_completion(printer_name, os.path.basename(temp_path), timeout=120):
                                    success_count += 1
                                    self.log(f"✅ Copy {copy_num + 1} completed in queue")
                                else:
                                    self.log(f"❌ Copy {copy_num + 1} failed queue monitoring")
                            else:
                                self.log(f"❌ Adobe command failed for copy {copy_num + 1}: {stderr}")
                                
                        except subprocess.TimeoutExpired:
                            self.log(f"⏰ Adobe process timed out for copy {copy_num + 1}")
                            process.kill()
                    
                    finally:
                        # 6. Clean up temp file
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                    
                    # 7. FORCE terminate Adobe processes after each job
                    time.sleep(3)
                    self._terminate_adobe_processes()
                    
                    # 8. Strict delay between copies
                    if copy_num < copies - 1:
                        self.log("⏰ Waiting 15 seconds between Adobe jobs...")
                        time.sleep(15)
                        
                except Exception as e:
                    self.log(f"❌ Error with Adobe copy {copy_num + 1}: {e}")
                    self._terminate_adobe_processes()
            
            # Final cleanup
            self._terminate_adobe_processes()
            
            if success_count >= max(1, copies // 2):
                self.log(f"✅ Adobe Reader successful: {success_count}/{copies} copies")
                return True
            else:
                self.log(f"❌ Adobe Reader insufficient success: {success_count}/{copies} copies")
                return False
                
        except Exception as e:
            self.log(f"❌ Adobe Reader error: {e}")
            self._terminate_adobe_processes()
            return False

    def _terminate_adobe_processes(self):
        """FORCEFULLY terminate all Adobe Reader processes"""
        try:
            adobe_processes = [
                "AcroRd32.exe", 
                "Acrobat.exe", 
                "AdobeARM.exe",
                "armsvc.exe",
                "AdobeCollabSync.exe"
            ]
            
            for process_name in adobe_processes:
                try:
                    # Use taskkill with force flag
                    result = subprocess.run(
                        ["taskkill", "/f", "/im", process_name], 
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        self.log(f"🔪 Terminated {process_name}")
                except Exception as e:
                    self.debug_log(f"Could not terminate {process_name}: {e}")
                    
        except Exception as e:
            self.log(f"❌ Error terminating Adobe processes: {e}")

    def _monitor_print_queue_completion(self, printer_name: str, filename_part: str, timeout: int = 120) -> bool:
        """Monitor printer queue until job completes or timeout"""
        try:
            start_time = time.time()
            job_appeared = False
            
            self.log(f"👀 Monitoring print queue for '{filename_part}' (timeout: {timeout}s)")
            
            while (time.time() - start_time) < timeout:
                try:
                    handle = win32print.OpenPrinter(printer_name)
                    jobs = win32print.EnumJobs(handle, 0, -1, 1)
                    win32print.ClosePrinter(handle)
                    
                    # Check if our job is in queue
                    found_job = False
                    for job in jobs:
                        if filename_part in job['pDocument'] or os.path.basename(filename_part) in job['pDocument']:
                            found_job = True
                            job_appeared = True
                            self.debug_log(f"📄 Job found in queue: {job['pDocument']} (Status: {job['Status']})")
                            break
                    
                    # If job appeared and now disappeared, it's complete
                    if job_appeared and not found_job:
                        self.log("✅ Job completed (disappeared from queue)")
                        return True
                    
                    # If no jobs in queue and we've waited a bit, assume complete
                    if not jobs and job_appeared:
                        self.log("✅ Queue empty, job completed")
                        return True
                        
                except Exception as e:
                    self.debug_log(f"Error checking print queue: {e}")
                
                time.sleep(3)
            
            # Timeout - check if queue is empty (might indicate completion)
            try:
                handle = win32print.OpenPrinter(printer_name)
                jobs = win32print.EnumJobs(handle, 0, -1, 1)
                win32print.ClosePrinter(handle)
                
                if not jobs:
                    self.log("⏰ Timeout reached but queue is empty - assuming success")
                    return True
            except:
                pass
            
            self.log(f"⏰ Queue monitoring timed out after {timeout} seconds")
            return False
            
        except Exception as e:
            self.log(f"❌ Error monitoring print queue: {e}")
            return False

    def _secure_print_pdf(self, file_path: str, printer_name: str, copies: int, color: bool) -> bool:
        """Enhanced PDF printing with multiple fallback methods."""
        try:
            self.log(f"🔍 Starting enhanced PDF printing ({copies} copies)")

            # 1. Try Windows CMD-based printing first (most reliable)
            self.log("🔄 Trying Windows CMD-based printing...")
            if self._try_adobe_print(file_path, printer_name, copies):
                self.log("✅ PDF printed using Windows CMD methods")
                return True

            # 2. Try SumatraPDF if available
            sumatra_paths = [
                r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
                r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe"
            ]
            sumatra_exe = None
            for path in sumatra_paths:
                if os.path.exists(path):
                    sumatra_exe = path
                    self.log(f"✅ Found SumatraPDF at: {path}")
                    break

            if sumatra_exe:
                success_count = 0
                for i in range(copies):
                    cmd = [sumatra_exe, "-print-to", printer_name, "-silent", file_path]
                    result = subprocess.run(cmd, capture_output=True, timeout=30)
                    if result.returncode == 0:
                        success_count += 1
                        self.log(f"✅ SumatraPDF copy {i+1} sent successfully")
                    else:
                        self.log(f"❌ SumatraPDF copy {i+1} failed with return code: {result.returncode}")
                    time.sleep(1)

                if success_count >= (copies // 2):  # Accept partial success
                    self.log(f"✅ SumatraPDF printed {success_count}/{copies} copies")
                    return True

            # 3. Fallback: PowerShell PDF printing
            self.log("🔄 Trying PowerShell fallback...")
            if self._try_powershell_pdf_print(file_path, printer_name, copies, color):
                self.log("✅ PDF printed using PowerShell fallback")
                return True

            # 4. Fallback: Windows default PDF handler
            self.log("🔄 Trying Windows default fallback...")
            if self._try_windows_pdf_print(file_path, printer_name, copies):
                self.log("✅ PDF printed using Windows default fallback")
                return True

            self.log("❌ All PDF printing methods failed")
            return False

        except Exception as e:
            self.log(f"❌ Enhanced PDF print error: {str(e)}")
            return False

    def _try_sumatra_print(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Try printing with SumatraPDF."""
        try:
            sumatra_paths = [
                r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
                r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe"
            ]

            for sumatra_path in sumatra_paths:
                if os.path.exists(sumatra_path):
                    for i in range(copies):
                        cmd = [sumatra_path, "-print-to", printer_name, "-silent", file_path]
                        result = subprocess.run(cmd, capture_output=True, timeout=30)
                        if result.returncode != 0:
                            break
                        time.sleep(1)

                    if result.returncode == 0:
                        self.log("✅ PDF printed using SumatraPDF")
                        return True

            return False

        except Exception as e:
            self.debug_log(f"SumatraPDF method failed: {e}")
            return False

    def _try_adobe_print(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Enhanced PDF printing using Windows CMD commands for better reliability."""
        try:
            self.log(f"🖨️ Starting Windows CMD print job: {copies} copies to {printer_name}")

            # Ensure file path is absolute and exists
            if not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)
            
            if not os.path.exists(file_path):
                self.log(f"❌ File not found: {file_path}")
                return False

            self.log(f"📄 Printing file: {file_path}")
            self.log(f"🖨️ Using printer: {printer_name}")

            success_count = 0

            for copy_num in range(copies):
                self.log(f"🖨️ Processing copy {copy_num + 1}/{copies}")

                try:
                    # Method 1: Try PowerShell with Start-Process
                    ps_cmd = f'''
Start-Process -FilePath "{file_path}" -ArgumentList "/t","{printer_name}" -Wait -WindowStyle Hidden
'''
                    result = subprocess.run(['powershell', '-Command', ps_cmd], 
                                          capture_output=True, text=True, timeout=60)
                    
                    if result.returncode == 0:
                        success_count += 1
                        self.log(f"✅ Copy {copy_num + 1} sent via PowerShell")
                        time.sleep(2)
                        continue

                    # Method 2: Try direct CMD with rundll32
                    cmd_command = [
                        'rundll32.exe', 
                        'mshtml.dll,PrintHTML', 
                        f'"{file_path}"'
                    ]
                    
                    result = subprocess.run(cmd_command, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        success_count += 1
                        self.log(f"✅ Copy {copy_num + 1} sent via rundll32")
                        time.sleep(2)
                        continue

                    # Method 3: Try Windows print command with ShellExecute
                    try:
                        import win32api
                        result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                        if result > 32:
                            success_count += 1
                            self.log(f"✅ Copy {copy_num + 1} sent via ShellExecute")
                            time.sleep(2)
                            continue
                    except Exception as e:
                        self.log(f"⚠️ ShellExecute failed: {e}")

                    # Method 4: Try generic print command
                    try:
                        import win32api
                        result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                        if result > 32:
                            success_count += 1
                            self.log(f"✅ Copy {copy_num + 1} sent via generic print")
                            time.sleep(2)
                            continue
                    except Exception as e:
                        self.log(f"⚠️ Generic print failed: {e}")

                    self.log(f"❌ All methods failed for copy {copy_num + 1}")

                except Exception as copy_error:
                    self.log(f"❌ Error printing copy {copy_num + 1}: {str(copy_error)}")

            # Check overall success
            if success_count == copies:
                self.log(f"✅ All {copies} copies printed successfully")
                return True
            elif success_count > 0:
                self.log(f"⚠️ Partial success: {success_count}/{copies} copies printed")
                return True
            else:
                self.log(f"❌ All printing methods failed")
                return False

        except Exception as e:
            self.log(f"❌ Windows CMD printing error: {str(e)}")
            return False

    def _cleanup_adobe_processes(self):
        """Clean up any hanging Adobe processes."""
        try:
            if platform.system() == "Windows":
                # Kill any hanging Adobe processes
                adobe_processes = [
                    "AcroRd32.exe", 
                    "Acrobat.exe", 
                    "AdobeARM.exe",
                    "armsvc.exe"
                ]

                for process_name in adobe_processes:
                    try:
                        # Use taskkill to terminate processes
                        subprocess.run(
                            ["taskkill", "/f", "/im", process_name], 
                            capture_output=True, 
                            timeout=10
                        )
                    except:
                        pass

            self.debug_log("🧹 Adobe processes cleaned up")

        except Exception as e:
            self.debug_log(f"Error cleaning Adobe processes: {e}")

    def _wait_for_printer_processing(self, printer_name: str, timeout: int = 30):
        """Wait for printer to process the job."""
        try:
            start_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    # Check printer queue using Windows API
                    if PLATFORM_PRINTING == "windows":
                        printer_handle = win32print.OpenPrinter(printer_name)
                        try:
                            jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
                            if not jobs:  # No jobs in queue
                                self.debug_log(f"✅ Printer queue empty for {printer_name}")
                                return True
                            else:
                                active_jobs = len([job for job in jobs if job['Status'] == 0])
                                self.debug_log(f"⏳ {active_jobs} jobs still processing on {printer_name}")
                        finally:
                            win32print.ClosePrinter(printer_handle)
                except:
                    pass

                time.sleep(2)

            self.debug_log(f"⏰ Printer processing timeout for {printer_name}")
            return False

        except Exception as e:
            self.debug_log(f"Error waiting for printer: {e}")
            return False

    def _try_powershell_pdf_print(self, file_path: str, printer_name: str, copies: int, color: bool) -> bool:
        """Try printing with PowerShell using enhanced PDF handling."""
        try:
            color_setting = "True" if color else "False"

            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

try {{
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "{file_path}"
    $startInfo.Verb = "printto"
    $startInfo.Arguments = '"{printer_name}"'
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = "Hidden"
    $startInfo.UseShellExecute = $true

    $successCount = 0
    for ($i = 0; $i -lt {copies}; $i++) {{
        try {{
            $process = [System.Diagnostics.Diagnostics.Process]::Start($startInfo)
            if ($process) {{
                $process.WaitForExit(30000)  # Wait up to 30 seconds
                if ($process.ExitCode -eq 0) {{
                    $successCount++
                    Write-Host "Copy $($i+1) sent successfully"
                }} else {{
                    Write-Host "Copy $($i+1) failed with exit code: $($process.ExitCode)"
                }}
            }} else {{
                Write-Host "Failed to start process for copy $($i+1)"
            }}
        }} catch {{
            Write-Host "Error printing copy $($i+1): $_"
        }}

        if ($i -lt {copies} - 1) {{
            Start-Sleep -Seconds 2  # Small delay between copies
        }}
    }}

    if ($successCount -eq {copies}) {{
        Write-Host "All copies printed successfully"
        exit 0
    }} elseif ($successCount -gt 0) {{
        Write-Host "Partial success: $successCount/{copies} copies printed"
        exit 0
    }} else {{
        Write-Host "No copies printed successfully"
        exit 1
    }}

}} catch {{
    Write-Host "PowerShell PDF print error: $_"
    exit 1
}}
'''

            result = subprocess.run(['powershell', '-Command', ps_script], 
                                  capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                self.log("✅ PDF printed using PowerShell")
                return True
            else:
                self.log(f"❌ PowerShell method failed: {result.stderr}")
                return False

        except Exception as e:
            self.debug_log(f"PowerShell method failed: {e}")
            return False

    def _try_windows_pdf_print(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Try printing with Windows default PDF handler using enhanced methods."""
        try:
            success_count = 0

            for i in range(copies):
                copy_success = False

                # Method 1: Try printto verb with printer name
                try:
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result > 32:
                        copy_success = True
                        self.log(f"✅ Windows printto method succeeded for copy {i+1}")
                except Exception as e:
                    self.debug_log(f"Windows printto method failed for copy {i+1}: {e}")

                # Method 2: Try default print verb if printto failed
                if not copy_success:
                    try:
                        result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                        if result > 32:
                            copy_success = True
                            self.log(f"✅ Windows default print method succeeded for copy {i+1}")
                    except Exception as e:
                        self.debug_log(f"Windows default print method failed for copy {i+1}: {e}")

                # Method 3: Try using rundll32 for PDF printing
                if not copy_success:
                    try:
                        cmd = [
                            'rundll32.exe',
                            'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
                            file_path,
                            printer_name
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                        if result.returncode == 0:
                            copy_success = True
                            self.log(f"✅ Windows rundll32 method succeeded for copy {i+1}")
                    except Exception as e:
                        self.debug_log(f"Windows rundll32 method failed for copy {i+1}: {e}")

                if copy_success:
                    success_count += 1
                    time.sleep(2)  # Small delay between copies
                else:
                    self.log(f"❌ All Windows methods failed for copy {i+1}")

            if success_count == copies:
                self.log("✅ All copies printed using Windows default methods")
                return True
            elif success_count > 0:
                self.log(f"⚠️ Partial success: {success_count}/{copies} copies printed via Windows methods")
                return True
            else:
                self.log("❌ All Windows PDF printing methods failed")
                return False

        except Exception as e:
            self.debug_log(f"Windows PDF print failed: {e}")
            return False

    def _print_image_sequential(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Sequential image printing with queue monitoring"""
        try:
            self.log(f"🖼️ Sequential image printing ({copies} copies)")
            
            for copy_num in range(copies):
                self.log(f"🖨️ Printing image copy {copy_num + 1}/{copies}")
                
                try:
                    # Method 1: Windows Photo Viewer
                    cmd = [
                        'rundll32.exe',
                        'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
                        file_path,
                        printer_name
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    
                    if result.returncode == 0:
                        # Monitor queue completion
                        if self._monitor_print_queue_completion(printer_name, os.path.basename(file_path), timeout=60):
                            self.log(f"✅ Image copy {copy_num + 1} completed")
                        else:
                            self.log(f"❌ Image copy {copy_num + 1} failed queue monitoring")
                            return False
                    else:
                        self.log(f"❌ Image copy {copy_num + 1} command failed")
                        return False
                    
                    # Delay between copies
                    if copy_num < copies - 1:
                        time.sleep(5)
                        
                except Exception as e:
                    self.log(f"❌ Error printing image copy {copy_num + 1}: {e}")
                    return False
            
            self.log("✅ All image copies printed successfully")
            return True
            
        except Exception as e:
            self.log(f"❌ Sequential image print error: {e}")
            return False

    def _print_generic_sequential(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Sequential generic file printing with queue monitoring"""
        try:
            self.log(f"📄 Sequential generic file printing ({copies} copies)")
            
            for copy_num in range(copies):
                self.log(f"🖨️ Printing generic file copy {copy_num + 1}/{copies}")
                
                try:
                    import win32api
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                    
                    if result > 32:
                        # Monitor queue completion
                        if self._monitor_print_queue_completion(printer_name, os.path.basename(file_path), timeout=60):
                            self.log(f"✅ Generic file copy {copy_num + 1} completed")
                        else:
                            self.log(f"❌ Generic file copy {copy_num + 1} failed queue monitoring")
                            return False
                    else:
                        self.log(f"❌ Generic file copy {copy_num + 1} command failed")
                        return False
                    
                    # Delay between copies
                    if copy_num < copies - 1:
                        time.sleep(5)
                        
                except Exception as e:
                    self.log(f"❌ Error printing generic file copy {copy_num + 1}: {e}")
                    return False
            
            self.log("✅ All generic file copies printed successfully")
            return True
            
        except Exception as e:
            self.log(f"❌ Sequential generic file print error: {e}")
            return False

    def _try_windows_pdf_sequential(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Sequential Windows PDF printing with queue monitoring"""
        try:
            self.log(f"🪟 Sequential Windows PDF printing ({copies} copies)")
            
            for copy_num in range(copies):
                self.log(f"🖨️ Windows PDF copy {copy_num + 1}/{copies}")
                
                success = False
                
                # Method 1: printto verb
                try:
                    import win32api
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result > 32:
                        success = True
                        self.log(f"✅ Windows printto successful for copy {copy_num + 1}")
                except Exception as e:
                    self.log(f"⚠️ Windows printto failed: {e}")
                
                # Method 2: print verb fallback
                if not success:
                    try:
                        import win32api
                        result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                        if result > 32:
                            success = True
                            self.log(f"✅ Windows print successful for copy {copy_num + 1}")
                    except Exception as e:
                        self.log(f"⚠️ Windows print failed: {e}")
                
                if success:
                    # Monitor queue completion
                    if not self._monitor_print_queue_completion(printer_name, os.path.basename(file_path), timeout=60):
                        self.log(f"❌ Copy {copy_num + 1} failed queue monitoring")
                        return False
                else:
                    self.log(f"❌ All Windows methods failed for copy {copy_num + 1}")
                    return False
                
                # Delay between copies
                if copy_num < copies - 1:
                    time.sleep(5)
            
            self.log("✅ All Windows PDF copies printed successfully")
            return True
            
        except Exception as e:
            self.log(f"❌ Sequential Windows PDF print error: {e}")
            return False

    def _handle_passport_photo_printing_sequential(self, file_path: str, printer_name: str, filename: str, print_settings: Dict) -> bool:
        """Sequential passport photo printing with layout creation"""
        try:
            self.log("📸 Sequential passport photo processing...")
            
            # Get number of photos for layout
            total_prints = print_settings.get('copies', 8)
            if total_prints not in (8, 16, 30):
                self.log(f"❌ Unsupported number of passport photos: {total_prints}")
                return False
            
            # Create unique output path
            output_fd, output_path = tempfile.mkstemp(suffix='.jpg', prefix='passport_layout_')
            os.close(output_fd)
            
            try:
                # Create passport photo layout
                self.log(f"🔄 Creating passport photo layout for {total_prints} photos...")
                layout_success = create_passport_photo_layout(file_path, output_path, total_prints=total_prints)
                
                if not layout_success:
                    self.log("❌ Failed to create passport photo layout")
                    return False
                
                # Print the layout (only 1 copy since layout contains all photos)
                self.log("🖨️ Printing passport photo layout...")
                success = self._print_image_sequential(output_path, printer_name, 1)
                
                if success:
                    self.log("✅ Passport photos printed successfully!")
                    self.log(f"📄 {total_prints} passport-size photos on one A4 page")
                    return True
                else:
                    self.log("❌ Failed to print passport photo layout")
                    return False
                    
            finally:
                # Clean up layout file
                try:
                    os.remove(output_path)
                except:
                    pass
                    
        except Exception as e:
            self.log(f"❌ Sequential passport photo error: {e}")
            return False

    def _secure_print_image(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Secure image printing."""
        try:
            self.log(f"🖼️  Printing image ({copies} copies)")

            for i in range(copies):
                # Try multiple methods for reliability
                success = False

                # Method 1: Use printto verb
                try:
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result > 32:
                        success = True
                except:
                    pass

                # Method 2: Use print verb
                if not success:
                    try:
                        result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                        if result > 32:
                            success = True
                    except:
                        pass

                if not success:
                    self.log(f"❌ Failed to print image copy {i+1}")
                    return False

                time.sleep(2)

            self.log("✅ Image printed successfully")
            return True

        except Exception as e:
            self.log(f"❌ Image print error: {str(e)}")
            return False

    def _secure_print_document(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Secure document printing for Word/text files."""
        try:
            self.log(f"📄 Printing document ({copies} copies)")

            for i in range(copies):
                try:
                    # Use Windows default handler
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result <= 32:
                        # Fallback to print verb
                        result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                        if result <= 32:
                            return False

                    time.sleep(3)  # Wait for application to process

                except Exception as e:
                    self.log(f"❌ Error printing document copy {i+1}: {e}")
                    return False

            self.log("✅ Document printed successfully")
            return True

        except Exception as e:
            self.log(f"❌ Document print error: {str(e)}")
            return False

    def _secure_print_generic(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Generic secure printing for unknown file types."""
        try:
            self.log(f"📄 Printing generic file ({copies} copies)")

            for i in range(copies):
                try:
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                    if result <= 32:
                        self.log(f"❌ Failed to print generic file copy {i+1}")
                        return False

                    time.sleep(2)

                except Exception as e:
                    self.log(f"❌ Error printing generic file copy {i+1}: {e}")
                    return False

            self.log("✅ Generic file printed successfully")
            return True

        except Exception as e:
            self.log(f"❌ Generic print error: {str(e)}")
            return False

    def _secure_delete_file(self, file_path: str):
        """Securely delete a file with overwrite."""
        try:
            if os.path.exists(file_path):
                # Get file size for secure overwrite
                file_size = os.path.getsize(file_path)

                # Overwrite with random data (2 passes for speed)
                with open(file_path, 'r+b') as f:
                    for _ in range(2):
                        f.seek(0)
                        f.write(os.urandom(file_size))
                        f.flush()
                        os.fsync(f.fileno())

                # Remove file
                os.remove(file_path)
                self.debug_log(f"🗑️  Securely deleted: {os.path.basename(file_path)}")

        except Exception as e:
            self.debug_log(f"⚠️  Could not securely delete {file_path}: {e}")
            # Fallback to regular deletion
            try:
                os.remove(file_path)
            except:
                pass

    def _print_cups_with_settings(self, document_data: bytes, printer_name: str, 
                                filename: str, print_settings: Dict) -> bool:
        """Print document on Linux/Mac using CUPS with settings and wait for completion."""
        try:
            conn = cups.Connection()
            job_name = f"AutoPrint: {filename}"

            # Prepare CUPS options based on settings
            options = {}

            if print_settings.get('copies', 1) > 1:
                options['copies'] = str(print_settings['copies'])

            if print_settings.get('color') == 'color':
                options['ColorModel'] = 'RGB'
            else:
                options['ColorModel'] = 'Gray'

            if print_settings.get('orientation') == 'landscape':
                options['orientation-requested'] = '4'

            # Create temporary file-like object
            doc_stream = io.BytesIO(document_data)

            # Print the document
            job_id = conn.printFile(printer_name, doc_stream, job_name, options)

            if job_id > 0:
                self.log(f"✅ Print job sent successfully (Job ID: {job_id})")

                # Wait for job completion
                completion_success = self._monitor_cups_job(conn, job_id, filename)

                if completion_success:
                    self.log(f"✅ Print job {job_id} completed successfully")
                    return True
                else:
                    self.log(f"❌ Print job {job_id} failed or did not complete")
                    return False
            else:
                self.log(f"❌ Print job failed - invalid job ID: {job_id}")
                return False

        except Exception as e:
            self.log(f"❌ CUPS printing error: {str(e)}")
            return False

    def _monitor_cups_job(self, conn, job_id: int, filename: str, timeout: int = 300) -> bool:
        """Monitor CUPS job until completion with enhanced tracking."""
        try:
            start_time = time.time()
            last_state = None

            self.log(f"📊 Monitoring CUPS job {job_id} for '{filename}' (timeout: {timeout}s)")

            while (time.time() - start_time) < timeout:
                try:
                    job_attrs = conn.getJobAttributes(job_id)
                    job_state = job_attrs.get('job-state', 0)
                    job_state_reasons = job_attrs.get('job-state-reasons', [])
                    job_state_message = job_attrs.get('job-state-message', '')

                    # Log state changes
                    if job_state != last_state:
                        state_names = {
                            3: "pending", 4: "held", 5: "processing", 
                            6: "stopped", 7: "canceled", 8: "aborted", 9: "completed"
                        }
                        state_name = state_names.get(job_state, f"unknown({job_state})")
                        self.log(f"🔄 CUPS job {job_id} state: {state_name}")
                        last_state = job_state

                    # Job states: 3=pending, 4=held, 5=processing, 6=stopped, 7=canceled, 8=aborted, 9=completed
                    if job_state == 9:  # completed
                        self.log(f"✅ CUPS job {job_id} completed successfully")
                        return True
                    elif job_state in [7, 8]:  # canceled or aborted
                        self.log(f"❌ CUPS job {job_id} failed (state: {job_state})")
                        if job_state_reasons:
                            self.log(f"   Reasons: {', '.join(job_state_reasons)}")
                        if job_state_message:
                            self.log(f"   Message: {job_state_message}")
                        return False
                    elif job_state == 6:  # stopped
                        self.log(f"⚠️ CUPS job {job_id} stopped")
                        if job_state_reasons:
                            self.log(f"   Reasons: {', '.join(job_state_reasons)}")
                        return False
                    elif job_state == 4:  # held
                        self.log(f"⏸️ CUPS job {job_id} is held - checking if it will resume")
                        # Continue monitoring as held jobs might resume

                    time.sleep(3)  # Check every 3 seconds

                except Exception as attr_error:
                    # Job might have completed and been removed
                    error_msg = str(attr_error).lower()

                    if "not found" in error_msg or "does not exist" in error_msg:
                        # Job no longer exists, likely completed
                        self.log(f"✅ CUPS job {job_id} completed (removed from system)")
                        return True
                    else:
                        self.debug_log(f"Error getting job attributes: {str(attr_error)}")

                    # Try to check if job is still in active jobs list
                    try:
                        jobs = conn.getJobs(which_jobs='not-completed')
                        if job_id not in jobs:
                            # Job not in active jobs, assume completed
                            self.log(f"✅ CUPS job {job_id} completed (not in active jobs)")
                            return True
                    except Exception as jobs_error:
                        self.debug_log(f"Error checking jobs list: {str(jobs_error)}")

                    time.sleep(5)  # Wait longer on error

            # Timeout reached
            elapsed_time = time.time() - start_time
            self.log(f"⏰ CUPS job monitoring timed out after {timeout} seconds")

            # Final check - sometimes jobs complete but we missed it
            try:
                jobs = conn.getJobs(which_jobs='not-completed')
                if job_id not in jobs:
                    self.log(f"✅ CUPS job {job_id} actually completed (final check)")
                    return True
            except:
                pass

            return False

        except Exception as e:
            self.log(f"❌ Error monitoring CUPS job: {str(e)}")
            return False

    def notify_job_completed(self, filename: str):
        """Notify the backend that a job has been completed via WebSocket."""
        if self.ws and self.ws.sock:
            try:
                payload = {
                    'type': 'job_completed',
                    'filename': filename,
                    'vendor_id': self.vendor_id
                }

                self.debug_log(f"📤 Notifying job completion: {filename}")
                self.ws.send(json.dumps(payload))

            except Exception as e:
                self.log(f"❌ Error notifying job completion: {str(e)}")

    def notify_job_failed(self, filename: str, error_message: str):
        """Notify the backend that a job has failed via WebSocket."""
        if self.ws and self.ws.sock:
            try:
                payload = {
                    'type': 'job_failed',
                    'filename': filename,
                    'error_message': error_message,
                    'vendor_id': self.vendor_id
                }

                self.debug_log(f"📤 Notifying job failure: {filename} - {error_message}")
                self.ws.send(json.dumps(payload))

            except Exception as e:
                self.log(f"❌ Error notifying job failure: {str(e)}")

    def update_r2_job_status(self, filename: str, status: str):
        """Update job completion status in R2 storage via API call."""
        try:
            # Convert WebSocket URL to HTTP URL for API calls
            api_base_url = self.base_url.replace('ws://', 'http://').replace('wss://', 'https://')
            api_url = f"{api_base_url}/update-job-status/"

            payload = {
                'filename': filename,
                'status': status,
                'vendor_id': self.vendor_id,
                'completion_time': time.time()
            }

            response = requests.post(api_url, json=payload, timeout=30)

            if response.status_code == 200:
                self.log(f"✅ Updated R2 storage status for {filename}: {status}")
            else:
                self.log(f"⚠️  Failed to update R2 status for {filename}: HTTP {response.status_code}")

        except Exception as e:
            self.log(f"❌ Error updating R2 job status: {str(e)}")

    def on_error(self, ws, error):
        """Handle WebSocket errors."""
        self.log(f"❌ WebSocket error: {str(error)}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close."""
        self.log("🔌 WebSocket connection closed")

        # Attempt to reconnect after a delay
        if self.is_running:
            self.log("🔄 Attempting to reconnect in 5 seconds...")
            time.sleep(5)
            self.connect_websocket()

    def on_open(self, ws):
        """Handle WebSocket connection open."""
        self.log("🔌 WebSocket connection established")

        # Start the job request loop
        threading.Thread(target=self.job_request_loop, daemon=True).start()

        # Start status monitoring
        threading.Thread(target=self.status_monitor_loop, daemon=True).start()

        # Send initial job request immediately
        try:
            self.ws.send(json.dumps({
                'type': 'request_print_jobs',
                'vendor_id': self.vendor_id
            }))
        except Exception as e:
            self.log(f"❌ Error sending initial job request: {str(e)}")

    def job_request_loop(self):
        """Continuously request print jobs every 60 seconds."""
        loop_count = 0
        while self.is_running and self.ws and self.ws.sock:
            try:
                # Only request if queue is not too full
                if self.print_queue.get_size() < 5:
                    self.debug_log("📤 Requesting new print jobs...")
                    self.ws.send(json.dumps({
                        'type': 'request_print_jobs',
                        'vendor_id': self.vendor_id
                    }))
                else:
                    self.debug_log("⏳ Skipping job request - queue is full")

                # Log status every 10 minutes
                loop_count += 1
                if loop_count % 10 == 0:  # Every 10 loops (10 minutes)
                    self.log_system_status()

                # Wait 60 seconds before next request
                time.sleep(60)

            except Exception as e:
                self.log(f"❌ Error in job request loop: {str(e)}")
                break

    def status_monitor_loop(self):
        """Monitor system status and performance"""
        while self.is_running:
            try:
                # Monitor queue sizes
                if self.print_queue.get_size() > 10:
                    self.log(f"⚠️  Large queue detected: {self.print_queue.get_size()} jobs pending")

                # Monitor failed jobs
                if self.failed_jobs_queue.get_size() > 5:
                    self.log(f"⚠️  Many failed jobs: {self.failed_jobs_queue.get_size()} jobs retrying")

                # Monitor printer status
                printer_stats = self.printer_manager.get_printer_stats()
                if printer_stats['error_printers'] > 0:
                    self.log(f"⚠️  {printer_stats['error_printers']} printers have errors")

                time.sleep(30)  # Check every 30 seconds

            except Exception as e:
                self.debug_log(f"Error in status monitor: {str(e)}")
                time.sleep(60)

    def log_system_status(self):
        """Log comprehensive system status"""
        printer_stats = self.printer_manager.get_printer_stats()

        self.log("📊 SYSTEM STATUS REPORT:")
        self.log(f"   📋 Queue Size: {self.print_queue.get_size()} jobs pending")
        self.log(f"   🔄 Failed Queue: {self.failed_jobs_queue.get_size()} jobs retrying")
        self.log(f"   🖨️  Printers: {printer_stats['idle_printers']} idle, {printer_stats['busy_printers']} busy, {printer_stats['error_printers']} error")
        self.log(f"   📈 Metrics: {self.job_metrics['total_completed']} completed, {self.job_metrics['total_failed']} failed")
        self.log(f"   ⏱️  Avg Processing: {self.job_metrics['average_processing_time']:.2f}s")

        # Log active processing threads
        active_threads = len([t for t in self.processing_threads.values() if not t.done()])
        self.log(f"   🧵 Active Threads: {active_threads}/{len(self.processing_threads)}")

    def connect_websocket(self):
        """Connect to WebSocket server."""
        # WebSocket URL
        ws_url = f"{self.base_url}/ws/vendor/{self.vendor_id}/"
        self.log(f"🔌 Connecting to WebSocket: {ws_url}")

        # Create WebSocket connection
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

    def run(self):
        """Main loop to continuously monitor for print jobs via WebSocket."""
        self.log("🔄 Starting Enhanced Automated Print Client")
        self.log(f"🖨️  Available printers: {self.printer_manager.get_printer_stats()['total_printers']}")

        # Enable WebSocket debug logging if debug mode is enabled
        if self.debug:
            websocket.enableTrace(True)

        while self.is_running:
            try:
                self.connect_websocket()
                # Run WebSocket connection (this blocks until connection closes)
                self.ws.run_forever()

            except KeyboardInterrupt:
                self.log("👋 Shutting down...")
                self.is_running = False
                break
            except Exception as e:
                self.log(f"💥 WebSocket error: {str(e)}")
                if self.is_running:
                    self.log("🔄 Retrying connection in 10 seconds...")
                    time.sleep(10)

        # Cleanup
        self.executor.shutdown(wait=True)
        self.log("🏁 Enhanced Print Client shutdown complete")

    def vendor_api_poller(self):
        """Background thread to poll vendor dashboard for print jobs via API."""
        while self.is_running:
            try:
                # Poll vendor dashboard for jobs
                self.log(f"🔄 Polling vendor dashboard for jobs...")

                payload = {
                    'vendor_id': self.vendor_id
                }

                response = requests.post(
                    self.vendor_api_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        jobs = data.get('jobs', [])
                        if jobs:
                            self.log(f"📋 Received {len(jobs)} jobs from vendor dashboard")
                            for job in jobs:
                                self.save_job_to_local_storage(job)
                        else:
                            self.log("📭 No jobs available from vendor dashboard")
                    else:
                        self.log(f"❌ Error from vendor dashboard: {data.get('error', 'Unknown error')}")
                else:
                    self.log(f"❌ HTTP error polling vendor dashboard: {response.status_code}")

            except Exception as e:
                self.log(f"❌ Error polling vendor dashboard: {e}")

            time.sleep(self.job_scan_interval)  # Poll every 10 seconds

    def save_job_to_local_storage(self, job):
        """Save job from vendor dashboard to local storage"""
        try:
            filename = job.get('filename', 'unknown.pdf')
            token = job.get('metadata', {}).get('token') or job.get('metadata', {}).get('job_id') or filename.split('.')[0]

            if token in self.seen_tokens:
                return  # Already processed this job

            # Create local job directory structure
            vendor_job_dir = os.path.join(self.job_dir, 'vendor_jobs')
            os.makedirs(vendor_job_dir, exist_ok=True)

            # Save job metadata as JSON
            job_file_path = os.path.join(vendor_job_dir, f'{token}.json')
            job_data = {
                'document_url': job.get('download_url'),
                'metadata': job.get('metadata', {}),
                'service_type': job.get('metadata', {}).get('service_type', 'unknown'),
                'filename': filename,
                'vendor_id': self.vendor_id
            }

            with open(job_file_path, 'w', encoding='utf-8') as f:
                json.dump(job_data, f, indent=2)

            self.log(f"💾 Saved job to local storage: {job_file_path}")

            # Create job node and enqueue
            job_node = PrintJobNode(
                filename=filename,
                download_url=job.get('download_url'),
                metadata=job.get('metadata', {}),
                service_type=job.get('metadata', {}).get('service_type', 'unknown')
            )

            self.print_queue.enqueue(job_node)
            self.seen_tokens.add(token)
            self.log(f"📋 Enqueued job from vendor dashboard: {filename}")

            if not self.queue_processor_running:
                threading.Thread(target=self.process_print_queue, daemon=True).start()

        except Exception as e:
            self.log(f"❌ Error saving job to local storage: {e}")

    def job_directory_watcher(self):
        """Background thread to scan for new print job JSON files and enqueue them."""
        while self.is_running:
            try:
                # Poll from local vendor jobs folder
                vendor_job_dir = os.path.join(self.job_dir, 'vendor_jobs')
                os.makedirs(vendor_job_dir, exist_ok=True)

                # Scan for job files in vendor folder
                job_files = sorted(glob.glob(os.path.join(vendor_job_dir, '*.json')))
                for job_file in job_files:
                    token = Path(job_file).stem
                    if token in self.seen_tokens:
                        continue
                    try:
                        with open(job_file, 'r', encoding='utf-8') as f:
                            job_data = json.load(f)
                        # Validate required fields
                        if 'document_url' not in job_data or 'metadata' not in job_data:
                            self.log(f"❌ Invalid job file (missing fields): {job_file}")
                            continue
                        filename = job_data['metadata'].get('filename', f'{token}.pdf')
                        job_node = PrintJobNode(
                            filename=filename,
                            download_url=job_data['document_url'],
                            metadata=job_data['metadata'],
                            service_type=job_data.get('service_type', 'unknown')
                        )
                        self.print_queue.enqueue(job_node)
                        self.seen_tokens.add(token)
                        self.log(f"📋 Enqueued job from local storage: {job_file}")
                        if not self.queue_processor_running:
                            threading.Thread(target=self.process_print_queue, daemon=True).start()
                    except Exception as e:
                        self.log(f"❌ Error loading job file {job_file}: {e}")
            except Exception as e:
                self.log(f"❌ Error scanning local job directory: {e}")
            time.sleep(self.job_scan_interval)

    def poll_for_print_jobs(self):
        """Poll the Django API for new print jobs from vendor-specific folder"""
        while self.is_running:
            try:
                # Make API request to get vendor-specific print jobs
                response = requests.post(
                    f"{self.api_url}/get-vendor-print-jobs/",
                    headers={'Content-Type': 'application/json'},
                    json={'vendor_id': self.vendor_id},
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get('success') and data.get('jobs'):
                        print(f"📋 Found {len(data['jobs'])} vendor-specific print jobs from API")

                        for job in data['jobs']:
                            # Save job to local storage for processing
                            self.save_job_to_local_storage(job)

                    else:
                        print("📋 No new vendor-specific print jobs found")
                else:
                    self.log(f"❌ API request failed with status {response.status_code}")

            except requests.exceptions.RequestException as e:
                self.log(f"❌ API request error: {e}")
            except Exception as e:
                self.log(f"❌ Unexpected error in poll_for_print_jobs: {e}")

            time.sleep(self.poll_interval)

# --- HTTP POLLING FUNCTIONS ---
def poll_print_jobs():
    """Poll the Django API for new print jobs"""
    headers = {'Authorization': f'Token {API_TOKEN}'}
    try:
        resp = requests.post(API_URL, headers=headers, timeout=LONG_POLL_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get('jobs', [])
        logging.info(f"Polled {len(jobs)} jobs from API.")
        return jobs
    except Exception as e:
        error_logger.error(f"HTTP polling error: {e}")
        return []

def save_job_and_pdf(job):
    """Save job metadata and document in a token folder with original extension."""
    token = job['metadata'].get('token') or job['metadata'].get('job_id') or job['filename'].split('.')[0]
    if not token:
        error_logger.error(f"No token/job_id in job: {job}")
        return False
    # Get original extension
    filename = job.get('filename', f'{token}.pdf')
    ext = os.path.splitext(filename)[1] or '.pdf'
    token_dir = os.path.join(LOCAL_JOB_DIR, token)
    os.makedirs(token_dir, exist_ok=True)
    # Save metadata
    metadata_path = os.path.join(token_dir, 'metadata.json')
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump({'document_url': job['download_url'], 'metadata': job['metadata']}, f)
        logging.info(f"Saved job metadata: {metadata_path}")
    except Exception as e:
        error_logger.error(f"Failed to save job JSON: {e}")
        return False
    # Download document
    doc_path = os.path.join(token_dir, filename)
    for attempt in range(3):
        try:
            r = requests.get(job['download_url'], stream=True, timeout=30)
            r.raise_for_status()
            with open(doc_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            logging.info(f"Downloaded document: {doc_path}")
            return True
        except Exception as e:
            error_logger.error(f"Document download failed (attempt {attempt+1}): {e}")
            time.sleep(5)
    return False

def process_print_queue():
    """Robust sequential print job processor using Adobe Reader and queue monitoring."""
    import psutil
    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    os.makedirs(FAILED_JOB_DIR, exist_ok=True)
    processed_count = 0
    success_count = 0
    delay_between_jobs = 25  # seconds
    max_retries = 3
    while True:
        try:
            # Gather all jobs (JSON+PDF pairs) in LOCAL_JOB_DIR
            json_files = [f for f in os.listdir(LOCAL_JOB_DIR) if f.endswith('.json')]
            if not json_files:
                time.sleep(5)
                continue
            for json_file in json_files:
                try:
                    token = os.path.splitext(json_file)[0]
                    json_path = os.path.join(LOCAL_JOB_DIR, json_file)
                    pdf_path = os.path.join(LOCAL_JOB_DIR, f"{token}.pdf")
                    if not os.path.exists(pdf_path):
                        error_logger.error(f"PDF not found for job {token}")
                        continue
                    # Check PDF integrity
                    with open(pdf_path, 'rb') as f:
                        header = f.read(4)
                        if header != b'%PDF':
                            error_logger.error(f"File {pdf_path} is not a valid PDF")
                            os.rename(json_path, os.path.join(FAILED_JOB_DIR, json_file))
                            os.rename(pdf_path, os.path.join(FAILED_JOB_DIR, f"{token}.pdf"))
                            continue
                    # Read job info
                    with open(json_path, 'r', encoding='utf-8') as f:
                        job_data = json.load(f)
                    # Print PDF with retries
                    success = False
                    for attempt in range(1, max_retries+1):
                        # Ensure no Adobe Reader process is running
                        for proc in psutil.process_iter(['name']):
                            if proc.info['name'] and 'AcroRd32' in proc.info['name']:
                                try:
                                    proc.terminate()
                                except Exception:
                                    pass
                        time.sleep(2)
                        # Build Adobe command
                        adobe_paths = [
                            r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                            r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                            r"C:\Program Files\Adobe\Reader 11.0\Reader\AcroRd32.exe",
                            r"C:\Program Files (x86)\Adobe\Reader 11.0\Reader\AcroRd32.exe"
                        ]
                        adobe_exe = None
                        for path in adobe_paths:
                            if os.path.exists(path):
                                adobe_exe = path
                                break
                        if not adobe_exe:
                            error_logger.error("Adobe Reader not found. Please install Adobe Reader.")
                            break
                        printer_name = PRINTER_NAME
                        # Start Adobe Reader print job
                        proc = subprocess.Popen([adobe_exe, "/t", pdf_path, printer_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        # Wait a few seconds for job to enter queue
                        time.sleep(5)
                        # Monitor print queue
                        queue_success = monitor_print_queue_for_job(printer_name, os.path.basename(pdf_path), timeout=300)
                        # Terminate Adobe Reader after job
                        for p in psutil.process_iter(['name']):
                            if p.info['name'] and 'AcroRd32' in p.info['name']:
                                try:
                                    p.terminate()
                                except Exception:
                                    pass
                        proc.wait(timeout=10)
                        if queue_success:
                            logging.info(f"Printed job {token} successfully.")
                            success = True
                            break
                        else:
                            error_logger.error(f"Print failed for {token} (attempt {attempt})")
                            time.sleep(10)
                    if success:
                        # Delete files on success
                        os.remove(json_path)
                        if os.path.exists(pdf_path):
                            os.remove(pdf_path)
                        logging.info(f"Cleaned up job {token}")
                        success_count += 1
                    else:
                        # Move to failed_jobs
                        os.makedirs(FAILED_JOB_DIR, exist_ok=True)
                        os.rename(json_path, os.path.join(FAILED_JOB_DIR, json_file))
                        if os.path.exists(pdf_path):
                            os.rename(pdf_path, os.path.join(FAILED_JOB_DIR, f"{token}.pdf"))
                        error_logger.error(f"Moved failed job {token} to failed_jobs.")
                    processed_count += 1
                    # Wait between jobs
                    time.sleep(delay_between_jobs)
                except Exception as e:
                    error_logger.error(f"Error processing job {json_file}: {e}")
            time.sleep(2)
        except Exception as e:
            error_logger.error(f"Error in print queue processor: {e}")
            time.sleep(10)

def polling_main():
    """Main function for HTTP polling mode"""
    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    os.makedirs(FAILED_JOB_DIR, exist_ok=True)

    # Authenticate vendor before polling
    if not authenticate_vendor():
        print("Exiting: Vendor authentication required.")
        return

    # Start print queue processor in background
    print_queue_thread = threading.Thread(target=process_print_queue, daemon=True)
    print_queue_thread.start()
    logging.info("Started print queue processor.")

    print("🔄 Starting HTTP polling loop...")
    print("   Press Ctrl+C to stop")

    while True:
        try:
            jobs = poll_print_jobs()
            for job in jobs:
                # Only process jobs with job_completed == NO (remove service_type and file type filtering)
                if job['metadata'].get('job_completed', 'NO').upper() == 'NO':
                    save_job_and_pdf(job)
            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n🛑 Stopping HTTP polling...")
            break

        except Exception as e:
            error_logger.error(f"Error in polling loop: {e}")
            time.sleep(POLL_INTERVAL)

def print_jobs_from_local_storage():
    print("🔄 Printing all jobs from local storage...")
    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    os.makedirs(FAILED_JOB_DIR, exist_ok=True)
    json_files = [f for f in os.listdir(LOCAL_JOB_DIR) if f.endswith('.json')]
    for json_file in json_files:
        try:
            token = os.path.splitext(json_file)[0]
            json_path = os.path.join(LOCAL_JOB_DIR, json_file)
            pdf_path = os.path.join(LOCAL_JOB_DIR, f"{token}.pdf")
            if not os.path.exists(pdf_path):
                error_logger.error(f"PDF not found for job {token}")
                continue
            with open(json_path, 'r', encoding='utf-8') as f:
                job_data = json.load(f)
            # Check if PDF is valid
            with open(pdf_path, 'rb') as f:
                header = f.read(4)
                if header != b'%PDF':
                    error_logger.error(f"File {pdf_path} is not a valid PDF")
                    # Move to failed_jobs
                    os.rename(json_path, os.path.join(FAILED_JOB_DIR, json_file))
                    os.rename(pdf_path, os.path.join(FAILED_JOB_DIR, f"{token}.pdf"))
                    continue
            # Print PDF
            success = False
            for attempt in range(3):
                success = print_pdf_windows(pdf_path, PRINTER_NAME)
                if success:
                    logging.info(f"Printed job {token} successfully.")
                    break
                else:
                    error_logger.error(f"Print failed for {token} (attempt {attempt+1})")
                    time.sleep(10)
            if success:
                os.remove(json_path)
                os.remove(pdf_path)
                logging.info(f"Cleaned up job {token}")
            else:
                os.rename(json_path, os.path.join(FAILED_JOB_DIR, json_file))
                os.rename(pdf_path, os.path.join(FAILED_JOB_DIR, f"{token}.pdf"))
                error_logger.error(f"Moved failed job {token} to failed_jobs.")
        except Exception as e:
            error_logger.error(f"Error processing job {json_file}: {e}")
    print("✅ Done printing all jobs from local storage.")

def main():
    parser = argparse.ArgumentParser(description="Automated Vendor Print Client")
    parser.add_argument("--vendor-id", default=VENDOR_ID, help="Vendor ID for authentication")
    parser.add_argument("--url", default=BASE_URL, help="Base URL of the Django server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--printer", help="Printer name to use as primary")
    parser.add_argument("--http-poll", action="store_true", help="Use HTTP polling mode to fetch jobs from website")
    parser.add_argument("--print-local", action="store_true", help="Print all jobs from local storage only (legacy)")
    parser.add_argument("--adobe-local-print", action="store_true", help="Print all jobs from local storage using Adobe Reader (robust mode)")
    parser.add_argument("--adobe-monitor-print", action="store_true", help="Print all PDFs from local storage using Adobe, monitor queue, and notify website")
    parser.add_argument("--test", action="store_true", help="Test printing functionality")
    parser.add_argument("--cmd-local-print", action="store_true", help="Process all jobs from local storage using enhanced CMD methods")

    print("🔧 Parsed arguments:")
    print(f"   --test: {args.test}")
    print(f"   --adobe-monitor-print: {args.adobe_monitor_print}")
    print(f"   --adobe-local-print: {args.adobe_local_print}")
    print(f"   --print-local: {args.print_local}")
    print(f"   --http-poll: {args.http_poll}")

    parser.add_argument("--cmd-local-print", action="store_true", help="Process all jobs from local storage using enhanced CMD methods")
    args = parser.parse_args()

    print("🔧 Parsed arguments:")
    print(f"   --test: {args.test}")
    print(f"   --cmd-local-print: {getattr(args, 'cmd_local_print', False)}")
    print(f"   --adobe-monitor-print: {args.adobe_monitor_print}")
    print(f"   --adobe-local-print: {args.adobe_local_print}")
    print(f"   --print-local: {args.print_local}")
    print(f"   --http-poll: {args.http_poll}")

    if args.test:
        print("🧪 Running test mode...")
        test_printing_functionality()
        sys.exit(0)
    elif getattr(args, 'cmd_local_print', False):
        print("🖨️ Running CMD-based local print mode...")
        process_all_local_jobs_cmd()
        sys.exit(0)
    elif args.adobe_monitor_print:
        print("🔄 Running adobe monitor print mode...")
        print_and_notify_adobe()
        sys.exit(0)
    elif args.adobe_local_print:
        print("🖨️ Running adobe local print mode...")
        adobe_local_print_jobs()
        sys.exit(0)
    elif args.print_local:
        print("🖨️ Running print local mode...")
        print_jobs_from_local_storage()
        sys.exit(0)
    elif args.http_poll:
        print("🔄 Running HTTP polling mode...")
        polling_main()
        sys.exit(0)

    # Default: Start enhanced vendor client
    print("🚀 Starting enhanced vendor client...")
    try:
        client = AutomatedVendorPrintClient(
            vendor_id=args.vendor_id,
            base_url=args.url,
            debug=args.debug,
            primary_printer=args.printer
        )
        client.run()
    except Exception as e:
        print(f"❌ Error starting vendor client: {e}")
        sys.exit(1)

def test_printing_functionality():
    """Test printing functionality to verify it works before running vendor client."""
    print("🧪 TESTING PRINTING FUNCTIONALITY")
    print("=" * 50)

    # Test printer detection
    print("1. Testing printer detection...")
    working_printer = find_working_printer()
    if working_printer:
        print(f"   ✅ Found working printer: {working_printer}")
    else:
        print("   ❌ No working printer found!")
        return False

    # Test PDF printing with a simple test
    print("2. Testing PDF printing...")
    try:
        # Create a simple test PDF using PowerShell
        test_pdf_script = '''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing

try {
    $doc = New-Object System.Drawing.Printing.PrintDocument
    $doc.DocumentName = "Test Document"

    $printPage = {
        param($sender, $e)
        $font = New-Object System.Drawing.Font("Arial", 12)
        $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::Black)
        $e.Graphics.DrawString("Test Print Job - Vendor Client", $font, $brush, 100, 100)
        $e.Graphics.DrawString("If you can see this, printing is working!", $font, $brush, 100, 150)
        $font.Dispose()
        $brush.Dispose()
    }

    $doc.add_PrintPage($printPage)
    $doc.Print()
    $doc.Dispose()

    Write-Host "Test print job sent successfully"
    exit 0
} catch {
    Write-Host "Test print failed: $_"
    exit 1
}
'''

        result = subprocess.run(['powershell', '-Command', test_pdf_script], 
                              capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print("   ✅ Test print job sent successfully!")
            print("   📄 Check your printer for a test page")
        else:
            print(f"   ❌ Test print failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"   ❌ Test print error: {e}")
        return False

    print("=" * 50)
    print("✅ Printing functionality test completed!")
    print("   You can now run the vendor client with confidence.")
    return True

def print_pdf_windows(file_path, printer_name=None):
    """Print PDF on Windows using Adobe Reader or SumatraPDF."""
    # Try Adobe Reader
    adobe_paths = [
        r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
        r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe"
    ]
    for adobe_path in adobe_paths:
        if os.path.exists(adobe_path):
            if printer_name:
                cmd = [adobe_path, "/t", file_path, printer_name]
            else:
                cmd = [adobe_path, "/t", file_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
    # Try SumatraPDF
    sumatra_paths = [
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe"
    ]
    for sumatra_path in sumatra_paths:
        if os.path.exists(sumatra_path):
            if printer_name:
                cmd = [sumatra_path, "-print-to", printer_name, file_path]
            else:
                cmd = [sumatra_path, "-print-to-default", file_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
    # If all else fails, log error
    error_logger.error(f"All PDF print methods failed for {file_path}")
    return False

class AdobePrintService:
    def __init__(self):
        self.adobe_paths = [
            r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            r"C:\Program Files\Adobe\Reader 11.0\Reader\AcroRd32.exe",
            r"C:\Program Files (x86)\Adobe\Reader 11.0\Reader\AcroRd32.exe"
        ]
        self.adobe_exe = None
        self.find_adobe_reader()
    def find_adobe_reader(self):
        for path in self.adobe_paths:
            if os.path.exists(path):
                self.adobe_exe = path
                logging.info(f"Found Adobe Reader: {path}")
                return True
        logging.error("Adobe Reader not found. Please install Adobe Reader.")
        return False
    def get_default_printer(self):
        try:
            result = subprocess.run(
                ['wmic', 'printer', 'where', 'default=true', 'get', 'name'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip() and line.strip() != 'Name':
                        return line.strip()
        except Exception as e:
            logging.error(f"Error getting default printer: {e}")
        return None
    def download_pdf(self, url):
        try:
            logging.info(f"Downloading PDF from: {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                temp_path = temp_file.name
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                logging.info(f"PDF downloaded to {temp_path}")
                return temp_path
        except Exception as e:
            logging.error(f"Error downloading PDF: {e}")
            return None
    def print_pdf_adobe(self, pdf_path, metadata, printer_name=None):
        """Print PDF using Adobe Reader with enhanced error handling."""
        if not self.adobe_exe:
            print("❌ Adobe Reader not available")
            return False
        
        try:
            # Validate PDF file exists
            if not os.path.exists(pdf_path):
                print(f"❌ PDF file not found: {pdf_path}")
                return False
            
            # Get printer name if not provided
            if not printer_name:
                printer_name = self.get_default_printer()
                if not printer_name:
                    print("❌ No printer found")
                    return False
            
            print(f"🖨️ Using printer: {printer_name}")
            print(f"📄 Printing: {os.path.basename(pdf_path)}")
            
            # Build Adobe command
            cmd = [self.adobe_exe, "/t", pdf_path, printer_name]
            print(f"🔧 Command: {' '.join(cmd)}")
            
            # Execute Adobe print command
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            try:
                # Wait for process to complete with timeout
                stdout, stderr = process.communicate(timeout=60)
                
                if process.returncode == 0:
                    print("✅ Adobe print command executed successfully")
                    
                    # Wait a bit for the print job to be sent to printer
                    time.sleep(3)
                    
                    # Clean up Adobe processes
                    self.close_adobe_reader()
                    
                    return True
                else:
                    print(f"❌ Adobe print command failed with return code: {process.returncode}")
                    if stderr:
                        error_msg = stderr.decode().strip()
                        if error_msg:
                            print(f"   Error details: {error_msg}")
                    return False
                    
            except subprocess.TimeoutExpired:
                print("⏰ Adobe print command timed out")
                process.kill()
                return False
                
        except Exception as e:
            print(f"❌ Error printing PDF: {e}")
            return False
    def close_adobe_reader(self):
        try:
            subprocess.run(['taskkill', '/f', '/im', 'AcroRd32.exe'], capture_output=True, check=False)
            subprocess.run(['taskkill', '/f', '/im', 'Acrobat.exe'], capture_output=True, check=False)
            logging.info("Adobe Reader processes closed")
        except Exception as e:
            logging.error(f"Error closing Adobe Reader: {e}")
    def process_print_job(self, job_data):
        try:
            if isinstance(job_data, str):
                job_data = json.loads(job_data)
            document_url = job_data.get('document_url')
            metadata = job_data.get('metadata', {})
            if not document_url:
                logging.error("No document URL provided in job data")
                return False
            pdf_path = self.download_pdf(document_url)
            if not pdf_path:
                return False
            try:
                success = self.print_pdf_adobe(pdf_path, metadata)
                if success:
                    logging.info("✓ Print job completed successfully!")
                    return True
                else:
                    logging.error("✗ Print job failed")
                    return False
            finally:
                try:
                    os.unlink(pdf_path)
                    logging.info("Temporary file cleaned up")
                except Exception as e:
                    logging.warning(f"Could not clean up temporary file: {e}")
        except Exception as e:
            logging.error(f"Error processing print job: {e}")
            return False

    def process_print_job_local(self, job_data):
        """
        Print a local file using Adobe Reader, using metadata for settings.
        Expects job_data to have 'metadata' and 'local_file_path'.
        """
        try:
            metadata = job_data.get('metadata', {})
            file_path = job_data.get('local_file_path')
            if not file_path or not os.path.exists(file_path):
                logging.error("No local file found for print job")
                return False
            return self.print_pdf_adobe(file_path, metadata)
        except Exception as e:
            logging.error(f"Error processing local print job: {e}")
            return False


def print_image_windows(image_path, printer_name=None):
    """Print an image file using Windows Photo Viewer or default print command."""
    try:
        print(f"🖼️ Printing image: {os.path.basename(image_path)}")
        
        # Try Windows Photo Viewer (works on most Windows 10/11)
        cmd = [
            'rundll32.exe',
            'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
            image_path,
            printer_name or ''
        ]
        
        print(f"🔧 Command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ Image printed successfully using Windows Photo Viewer")
            return True
        else:
            print(f"❌ Windows Photo Viewer print failed: {result.stderr}")
            
            # Fallback: Try generic print
            print("🔄 Trying generic print as fallback...")
            try:
                result = win32api.ShellExecute(0, "print", image_path, None, ".", 0)
                if result > 32:
                    print("✅ Generic print successful")
                    return True
                else:
                    print("❌ Generic print failed")
                    return False
            except Exception as e:
                print(f"❌ Generic print error: {e}")
                return False
                
    except Exception as e:
        print(f"❌ Error printing image: {e}")
        return False

def process_all_local_jobs_cmd():
    """
    Process all jobs in local storage using Windows CMD commands for maximum reliability.
    This method handles all file types and uses robust printing methods.
    """
    print("🔄 Starting CMD-based Local Print Jobs Processing...")
    print("=" * 60)
    
    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    os.makedirs(FAILED_JOB_DIR, exist_ok=True)
    
    working_printer = find_working_printer()
    if not working_printer:
        print("❌ No working printer found!")
        return

    print(f"🖨️ Using printer: {working_printer}")

    # Gather all jobs from different locations
    job_queue = []
    processed_count = 0
    success_count = 0
    
    # Check vendor_jobs subfolder first
    vendor_jobs_dir = os.path.join(LOCAL_JOB_DIR, 'vendor_jobs')
    if os.path.exists(vendor_jobs_dir):
        json_files = [f for f in os.listdir(vendor_jobs_dir) if f.endswith('.json')]
        for json_file in json_files:
            job_queue.append((os.path.join(vendor_jobs_dir, json_file), f"vendor_jobs/{json_file}"))
    
    # Check main directory for JSON files
    direct_json_files = [f for f in os.listdir(LOCAL_JOB_DIR) if f.endswith('.json')]
    job_queue.extend([(os.path.join(LOCAL_JOB_DIR, f), f) for f in direct_json_files])
    
    # Check for token subfolders with metadata.json
    subfolders = [f for f in os.listdir(LOCAL_JOB_DIR) if os.path.isdir(os.path.join(LOCAL_JOB_DIR, f)) and f != 'vendor_jobs']
    for subfolder in subfolders:
        subfolder_path = os.path.join(LOCAL_JOB_DIR, subfolder)
        metadata_file = os.path.join(subfolder_path, 'metadata.json')
        if os.path.exists(metadata_file):
            job_queue.append((metadata_file, f"{subfolder}/metadata.json"))

    if not job_queue:
        print("📭 No job files found in local storage.")
        print(f"   Checked locations:")
        print(f"   - {LOCAL_JOB_DIR}")
        print(f"   - {vendor_jobs_dir}")
        print(f"   - Token subfolders")
        return

    print(f"📋 Found {len(job_queue)} job files to process...")
    
    for json_path, json_file in job_queue:
        try:
            processed_count += 1
            print(f"\n📄 Processing job {processed_count}/{len(job_queue)}: {json_file}")
            
            with open(json_path, 'r', encoding='utf-8') as f:
                job_data = json.load(f)
            
            # Handle different job file formats
            if 'metadata' in job_data and 'document_url' in job_data:
                # New format from vendor dashboard
                metadata = job_data['metadata']
                document_url = job_data.get('document_url', '')
                filename = metadata.get('filename', 'document.pdf')
            elif 'metadata' in job_data and 'download_url' in job_data:
                # WebSocket format
                metadata = job_data['metadata']
                document_url = job_data.get('download_url', '')
                filename = metadata.get('filename', 'document.pdf')
            else:
                # Legacy format - job_data is the metadata
                metadata = job_data
                document_url = ''
                filename = metadata.get('filename', 'document.pdf')
            
            # Skip if already completed
            if metadata.get('job_completed', '').upper() == 'YES':
                print(f"   ✅ Job already completed, skipping: {filename}")
                continue
            
            service_type = metadata.get('service_type', '').lower()
            copies = int(metadata.get('copies', 1))
            
            print(f"   📄 File: {filename}")
            print(f"   🔧 Service: {service_type}")
            print(f"   📑 Copies: {copies}")
            
            # Try to find local file first
            json_dir = os.path.dirname(json_path)
            local_file_path = os.path.join(json_dir, filename)
            temp_file = None
            
            if os.path.exists(local_file_path):
                print(f"   ✅ Found local file: {os.path.basename(local_file_path)}")
                temp_file = local_file_path
            elif document_url:
                print(f"   ⬇️ Downloading from URL...")
                try:
                    response = requests.get(document_url, stream=True, timeout=30)
                    response.raise_for_status()
                    
                    file_ext = os.path.splitext(filename)[1] or '.pdf'
                    temp_fd, temp_path = tempfile.mkstemp(suffix=file_ext, prefix='print_job_')
                    temp_file = temp_path
                    
                    with os.fdopen(temp_fd, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    print(f"   ✅ Downloaded to: {os.path.basename(temp_path)}")
                except Exception as e:
                    print(f"   ❌ Download failed: {e}")
                    continue
            else:
                print(f"   ❌ No document URL and no local file found")
                continue
            
            # Print the document using CMD methods
            print("   🖨️ Sending to printer...")
            success = False
            
            try:
                file_ext = os.path.splitext(filename)[1].lower()
                
                if service_type == 'passport_photo':
                    # Create passport photo layout
                    layout_output_path = os.path.join(json_dir, f"passport_layout_{os.path.splitext(filename)[0]}.jpg")
                    layout_success = create_passport_photo_layout(temp_file, layout_output_path, total_prints=copies)
                    
                    if layout_success:
                        success = print_image_automatically(layout_output_path, working_printer)
                        try:
                            os.remove(layout_output_path)
                        except:
                            pass
                    else:
                        print("   ❌ Failed to create passport photo layout")
                
                elif file_ext == '.pdf':
                    # Use enhanced CMD-based PDF printing
                    success = print_pdf_cmd_enhanced(temp_file, working_printer, copies)
                
                elif file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif']:
                    success = print_image_cmd_enhanced(temp_file, working_printer)
                
                else:
                    print(f"   ⚠️ Unknown file type: {file_ext}, trying generic print...")
                    success = print_generic_cmd_enhanced(temp_file, working_printer)
                
            except Exception as e:
                print(f"   ❌ Printing error: {e}")
            
            # Cleanup temporary file
            if temp_file and os.path.exists(temp_file) and temp_file != local_file_path:
                try:
                    os.remove(temp_file)
                    print("   🗑️ Temporary file cleaned up")
                except Exception as e:
                    print(f"   ⚠️ Could not clean up temp file: {e}")
            
            if success:
                success_count += 1
                print("   ✅ Job completed successfully!")
                
                # Update job status to completed
                try:
                    metadata['job_completed'] = 'YES'
                    if 'metadata' in job_data:
                        job_data['metadata'] = metadata
                    else:
                        job_data = metadata
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(job_data, f, indent=2)
                    print("   📝 Updated job status to completed")
                except Exception as e:
                    print(f"   ⚠️ Could not update job status: {e}")
                
            else:
                print("   ❌ Job failed")
                
        except Exception as e:
            print(f"   ❌ Error processing {json_file}: {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 PROCESSING SUMMARY:")
    print(f"   📄 Total jobs processed: {processed_count}")
    print(f"   ✅ Successful prints: {success_count}")
    print(f"   ❌ Failed prints: {processed_count - success_count}")
    print(f"   📈 Success rate: {(success_count/processed_count*100):.1f}%" if processed_count > 0 else "   📈 Success rate: 0%")
    print("=" * 60)
    print("✅ CMD-based Local Print Jobs Processing completed!")

def print_pdf_cmd_enhanced(file_path, printer_name, copies=1):
    """Enhanced PDF printing using multiple CMD methods."""
    try:
        print(f"   🔍 Printing PDF: {os.path.basename(file_path)} ({copies} copies)")
        
        for copy_num in range(copies):
            success = False
            
            # Method 1: PowerShell with Start-Process
            try:
                ps_cmd = f'Start-Process -FilePath "{file_path}" -ArgumentList "/t","{printer_name}" -Wait -WindowStyle Hidden'
                result = subprocess.run(['powershell', '-Command', ps_cmd], 
                                      capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    success = True
                    print(f"   ✅ Copy {copy_num + 1} sent via PowerShell")
            except Exception as e:
                print(f"   ⚠️ PowerShell method failed: {e}")
            
            # Method 2: Try Windows print verb
            if not success:
                try:
                    import win32api
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result > 32:
                        success = True
                        print(f"   ✅ Copy {copy_num + 1} sent via printto")
                except Exception as e:
                    print(f"   ⚠️ Printto method failed: {e}")
            
            # Method 3: Generic print
            if not success:
                try:
                    import win32api
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                    if result > 32:
                        success = True
                        print(f"   ✅ Copy {copy_num + 1} sent via generic print")
                except Exception as e:
                    print(f"   ⚠️ Generic print failed: {e}")
            
            if not success:
                print(f"   ❌ All methods failed for copy {copy_num + 1}")
                return False
            
            time.sleep(2)  # Small delay between copies
        
        return True
        
    except Exception as e:
        print(f"   ❌ PDF printing error: {e}")
        return False

def print_image_cmd_enhanced(file_path, printer_name):
    """Enhanced image printing using CMD methods."""
    try:
        print(f"   🖼️ Printing image: {os.path.basename(file_path)}")
        
        # Method 1: Windows Photo Viewer
        try:
            cmd = [
                'rundll32.exe',
                'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
                file_path,
                printer_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print("   ✅ Image printed via Windows Photo Viewer")
                return True
        except Exception as e:
            print(f"   ⚠️ Photo Viewer failed: {e}")
        
        # Method 2: Generic print
        try:
            import win32api
            result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
            if result > 32:
                print("   ✅ Image printed via generic print")
                return True
        except Exception as e:
            print(f"   ⚠️ Generic print failed: {e}")
        
        return False
        
    except Exception as e:
        print(f"   ❌ Image printing error: {e}")
        return False

def print_generic_cmd_enhanced(file_path, printer_name):
    """Enhanced generic file printing using CMD methods."""
    try:
        print(f"   📄 Printing generic file: {os.path.basename(file_path)}")
        
        try:
            import win32api
            result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
            if result > 32:
                print("   ✅ Generic file printed")
                return True
        except Exception as e:
            print(f"   ⚠️ Generic print failed: {e}")
        
        return False
        
    except Exception as e:
        print(f"   ❌ Generic file printing error: {e}")
        return False

def adobe_local_print_jobs():
    """Process all jobs in local storage using Adobe Reader for PDFs, and Windows Photo Viewer for images, with robust queue and retry logic."""
    print("🔄 Starting Adobe Local Print Jobs...")
    print("=" * 50)
    print_service = AdobePrintService()
    if not print_service.adobe_exe:
        print("❌ Adobe Reader not found. Please install Adobe Reader.")
        print("   Download from: https://get.adobe.com/reader/")
        return

    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    os.makedirs(FAILED_JOB_DIR, exist_ok=True)
    working_printer = find_working_printer()
    if not working_printer:
        print("❌ No working printer found!")
        return

    # Gather all jobs
    job_queue = []
    # Check for JSON files directly in the main directory
    direct_json_files = [f for f in os.listdir(LOCAL_JOB_DIR) if f.endswith('.json')]
    job_queue.extend([(os.path.join(LOCAL_JOB_DIR, f), f) for f in direct_json_files])
    # Check for JSON files in subfolders
    subfolders = [f for f in os.listdir(LOCAL_JOB_DIR) if os.path.isdir(os.path.join(LOCAL_JOB_DIR, f))]
    for subfolder in subfolders:
        subfolder_path = os.path.join(LOCAL_JOB_DIR, subfolder)
        subfolder_json_files = [f for f in os.listdir(subfolder_path) if f.endswith('.json')]
        job_queue.extend([(os.path.join(subfolder_path, f), f"{subfolder}/{f}") for f in subfolder_json_files])

    if not job_queue:
        print("📭 No JSON job files found in local storage.")
        print(f"   Expected location: {LOCAL_JOB_DIR}")
        print("   Checked both main directory and subfolders")
        return

    print(f"📋 Found {len(job_queue)} job files to process...")
    max_retries = 3
    failed_jobs = {}
    processed_count = 0
    success_count = 0
    total_jobs = len(job_queue)
    # Use a queue system with retries
    while job_queue:
        json_path, json_file = job_queue.pop(0)
        try:
            processed_count += 1
            print(f"\n📄 Processing job {processed_count}/{total_jobs}: {json_file}")
            with open(json_path, 'r', encoding='utf-8') as f:
                job_data = json.load(f)
            filename = job_data.get('metadata', {}).get('filename', 'document.pdf')
            document_url = job_data.get('document_url', '')
            service_type = job_data.get('metadata', {}).get('service_type', '').lower()
            copies = int(job_data.get('metadata', {}).get('copies', 8))
            print(f"   📄 File: {filename}")
            json_dir = os.path.dirname(json_path)
            local_file_path = os.path.join(json_dir, filename)
            temp_file = None
            if os.path.exists(local_file_path):
                print(f"   ✅ Found local file: {os.path.basename(local_file_path)}")
                temp_file = local_file_path
            elif document_url:
                print(f"   🔗 URL: {document_url[:50]}...")
                print("   ⬇️ Downloading document...")
                try:
                    response = requests.get(document_url, stream=True, timeout=30)
                    response.raise_for_status()
                    file_ext = os.path.splitext(filename)[1] or '.jpg'
                    temp_fd, temp_path = tempfile.mkstemp(suffix=file_ext, prefix='print_job_')
                    temp_file = temp_path
                    with os.fdopen(temp_fd, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    print(f"   ✅ Downloaded to: {os.path.basename(temp_path)}")
                except Exception as e:
                    print(f"   ❌ Download failed: {e}")
                    continue
            else:
                print(f"   ❌ No document URL found and no local file: {filename}")
                continue
            print("   🖨️ Printing document...")
            success = False
            try:
                file_ext = os.path.splitext(filename)[1].lower()
                if service_type == 'passport_photo':
                    # Generate A4 layout for passport photos
                    layout_output_path = os.path.join(json_dir, f"passport_layout_{os.path.splitext(filename)[0]}.jpg")
                    layout_success = create_passport_photo_layout(temp_file, layout_output_path, total_prints=copies)
                    if not layout_success:
                        print("❌ Failed to create passport photo layout")
                        failed_jobs[json_path] = failed_jobs.get(json_path, 0) + 1
                        if failed_jobs[json_path] < max_retries:
                            print(f"   🔁 Retrying job ({failed_jobs[json_path]}/{max_retries})...")
                            job_queue.append((json_path, json_file))
                            time.sleep(5)
                        else:
                            print("   ❌ Max retries reached, moving to failed jobs.")
                        continue
                    print("   🖨️ Printing passport photo layout...")
                    success = print_image_automatically(layout_output_path, working_printer)
                    if os.path.exists(layout_output_path):
                        os.remove(layout_output_path)
                elif file_ext == '.pdf':
                    success = print_service.print_pdf_adobe(temp_file, job_data.get('metadata', {}), working_printer)
                    if success:
                        print("   ✅ PDF printed successfully using Adobe Reader")
                    else:
                        print("   ❌ PDF printing failed")
                elif file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif']:
                    success = print_image_windows(temp_file, working_printer)
                    if success:
                        print("   ✅ Image printed successfully using Windows Photo Viewer")
                    else:
                        print("   ❌ Image printing failed")
                else:
                    print(f"   ⚠️ Unknown file type: {file_ext}, trying generic print...")
                    try:
                        result = win32api.ShellExecute(0, "print", temp_file, None, ".", 0)
                        if result > 32:
                            success = True
                            print("   ✅ Generic print successful")
                        else:
                            print("   ❌ Generic print failed")
                    except Exception as e:
                        print(f"   ❌ Generic print error: {e}")
            except Exception as e:
                print(f"   ❌ Printing error: {e}")
            if temp_file and os.path.exists(temp_file) and temp_file != local_file_path:
                try:
                    os.remove(temp_file)
                    print("   🗑️ Temporary file cleaned up")
                except Exception as e:
                    print(f"   ⚠️ Could not clean up temp file: {e}")
            elif temp_file == local_file_path:
                print("   📁 Local file preserved")
            if success:
                success_count += 1
                print("   ✅ Job completed successfully!")
            else:
                print("   ❌ Job failed")
                failed_jobs[json_path] = failed_jobs.get(json_path, 0) + 1
                if failed_jobs[json_path] < max_retries:
                    print(f"   🔁 Retrying job ({failed_jobs[json_path]}/{max_retries})...")
                    job_queue.append((json_path, json_file))
                    time.sleep(5)
                else:
                    print("   ❌ Max retries reached, moving to failed jobs.")
        except Exception as e:
            print(f"   ❌ Error processing {json_file}: {e}")
            failed_jobs[json_path] = failed_jobs.get(json_path, 0) + 1
            if failed_jobs[json_path] < max_retries:
                print(f"   🔁 Retrying job ({failed_jobs[json_path]}/{max_retries})...")
                job_queue.append((json_path, json_file))
                time.sleep(5)
            else:
                print("   ❌ Max retries reached, moving to failed jobs.")
    print("\n" + "=" * 50)
    print(f"📊 PRINTING SUMMARY:")
    print(f"   📄 Total jobs processed: {processed_count}")
    print(f"   ✅ Successful prints: {success_count}")
    print(f"   ❌ Failed prints: {processed_count - success_count}")
    print(f"   📈 Success rate: {(success_count/processed_count*100):.1f}%" if processed_count > 0 else "   📈 Success rate: 0%")
    print("=" * 50)
    print("✅ Adobe Local Print Jobs completed!")

ADOBE_PATH = r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe"  # Path to Adobe Acrobat
WEBSITE_API_URL = "http://yourwebsite.com/api/job-status/"  # Replace with your API endpoint


def print_pdf_adobe_with_jobname(file_path, printer_name, job_name):
    """Send the PDF to the printer using Adobe Acrobat with a custom job name."""
    cmd = [ADOBE_PATH, "/t", file_path, printer_name]
    # Note: Adobe does not allow setting job name directly, but we can try to set the file name accordingly
    subprocess.run(cmd, check=True)


def monitor_print_queue_for_job(printer_name, job_name, timeout=300):
    """Monitor the print queue until the job is completed or timeout (in seconds)."""
    hprinter = win32print.OpenPrinter(printer_name)
    try:
        start_time = time.time()
        while time.time() - start_time < timeout:
            jobs = win32print.EnumJobs(hprinter, 0, 10, 1)
            found = False
            for job in jobs:
                if job_name in job['pDocument']:
                    print(f"Job {job['JobId']} still in queue, status: {job['Status']}")
                    found = True
                    break
            if not found:
                print(f"Job {job_name} has been printed.")
                return True
            time.sleep(5)
        print(f"Timeout waiting for job {job_name} to complete.")
        return False
    finally:
        win32print.ClosePrinter(hprinter)


def send_completion_status(token_number):
    """Send completion status to the website."""
    payload = {"token_number": token_number, "status": "completed"}
    try:
        response = requests.post(WEBSITE_API_URL, json=payload)
        response.raise_for_status()
        print(f"Status update sent for job {token_number}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send status update: {e}")


def print_and_notify_adobe():
    """
    For each job in local storage, print with Adobe (PDF) or Windows Photo Viewer (images),
    monitor queue, and notify website.
    """
    os.makedirs(LOCAL_JOB_DIR, exist_ok=True)
    token_folders = [f for f in os.listdir(LOCAL_JOB_DIR) if os.path.isdir(os.path.join(LOCAL_JOB_DIR, f))]
    for token in token_folders:
        try:
            token_dir = os.path.join(LOCAL_JOB_DIR, token)
            metadata_path = os.path.join(token_dir, 'metadata.json')
            if not os.path.exists(metadata_path):
                continue
            with open(metadata_path, 'r', encoding='utf-8') as f:
                job_data = json.load(f)
            doc_files = [f for f in os.listdir(token_dir) if f != 'metadata.json']
            if not doc_files:
                print(f"No document file found in {token_dir}")
                continue
            doc_path = os.path.join(token_dir, doc_files[0])
            ext = os.path.splitext(doc_path)[1].lower()
            job_name = f"Print Job {token}"
            printer_name = win32print.GetDefaultPrinter()
            print(f"Printing {doc_path} to {printer_name} as {job_name}")
            queue_success = False
            if ext == '.pdf':
                try:
                    print_pdf_adobe_with_jobname(doc_path, printer_name, job_name)
                    queue_success = monitor_print_queue_for_job(printer_name, os.path.basename(doc_path))
                except Exception as e:
                    print(f"Error printing PDF: {e}")
            elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']:
                try:
                    print_image_windows(doc_path, printer_name)
                    queue_success = monitor_print_queue_for_job(printer_name, os.path.basename(doc_path))
                except Exception as e:
                    print(f"Error printing image: {e}")
            else:
                print(f"Skipping unsupported file type: {doc_path}")
                continue
            if queue_success:
                send_completion_status(token)
            else:
                print(f"Failed to confirm print job completion for {token}")
        except Exception as e:
            print(f"Error processing job {token}: {e}")

# --- VENDOR CREDENTIALS (replace with your actual values) ---
VENDOR_EMAIL = "abd@gmail.com"
VENDOR_NAME = "abdshop"
VENDOR_ID = "5263393941"  # This matches your folder structure
VENDOR_TOKEN = "7911273877"
BASE_URL = "http://localhost:8000"  # Use localhost for local Django server

# --- AUTHENTICATION FUNCTION ---
def authenticate_vendor():
    url = f"{BASE_URL}/vendor-authenticate/"
    payload = {
        "vendor_email": VENDOR_EMAIL,
        "vendor_id": VENDOR_ID,
        "vendor_token": VENDOR_TOKEN,
        "shop_name": VENDOR_NAME
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get('success', False):
            print("✅ Vendor authentication successful!")
            return True
        else:
            print(f"❌ Vendor authentication failed: {data.get('error', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Error during authentication: {e}")
        return False

# --- INSTRUCTIONS FOR RUNNING ---
if __name__ == "__main__":
    # Install required packages check
    try:
        import PIL
    except ImportError:
        print("❌ Required package 'Pillow' not found!")
        print("   Please install it using: pip install Pillow")
        input("Press Enter to exit...")
        sys.exit(1)

    # Run the main function with proper argument parsing
    main()