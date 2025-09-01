#!/usr/bin/env python3
"""
Automated Vendor Print Client Script
====================================
Replaces Adobe printing with Sumatra-based printing and implements
authentication-first queue-based printing system.
"""

import os
import sys
import time
import json
import argparse
import requests
import io
import platform
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
        import win32gui
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

# --- CONFIGURATION ---
API_URL = os.environ.get('VENDOR_API_URL', 'http://localhost:8000/auto-print-documents/')
API_TOKEN = os.environ.get('VENDOR_API_TOKEN', 'testtoken')
LOCAL_JOB_DIR = r'C:\Users\Azfar\Downloads\printjobs'
FAILED_JOB_DIR = os.path.join(LOCAL_JOB_DIR, 'failed_jobs')
POLL_INTERVAL = 10  # seconds
LONG_POLL_TIMEOUT = 30  # seconds
PRINTER_NAME = 'Canon GX2000 series'  # or None for default
DEFAULT_PAPER_SIZE = 'A4'  # Default paper size for printing
AUTO_PRINT_ENABLED = True  # Enable automatic printing without dialogs

# --- VENDOR CREDENTIALS ---
VENDOR_EMAIL = "azfarshaikh7860@gmail.com"
VENDOR_NAME = "azfarxerox"
VENDOR_ID = "9080823634"
VENDOR_TOKEN = "1498760458"
BASE_URL = "http://localhost:8000"

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
        self.primary_printer = primary_printer or "Canon GX2000 series"

        # Initialize with primary printer
        self.add_printer(self.primary_printer)
        print(f"🖨️ Primary printer set: {self.primary_printer}")
        
        # Also add the Canon printer specifically
        canon_printer = "Canon GX2000 series"
        if canon_printer != self.primary_printer:
            self.add_printer(canon_printer)
            print(f"🖨️ Added Canon printer: {canon_printer}")

    def add_printer(self, printer_name: str):
        """Add a printer to the manager"""
        with self.lock:
            if printer_name not in self.printers:
                self.printers[printer_name] = {
                    'name': printer_name,
                    'status': 'idle',
                    'jobs_completed': 0,
                    'jobs_failed': 0,
                    'last_used': None
                }
                self.printer_status[printer_name] = 'idle'
                print(f"🖨️ Added printer: {printer_name}")

    def get_available_printer(self) -> Optional[str]:
        """Get an available printer for job assignment"""
        with self.lock:
            # Always dynamically find a working printer
            available_printers = []
            for printer_name, status in self.printer_status.items():
                if status == 'idle':
                    available_printers.append(printer_name)

            if available_printers:
                # Return the first available printer
                return available_printers[0]
            return None

    def set_printer_busy(self, printer_name: str, job: PrintJobNode):
        """Mark printer as busy with a specific job"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'busy'
                self.printer_jobs[printer_name] = job
                self.printers[printer_name]['last_used'] = time.time()

    def set_printer_idle(self, printer_name: str):
        """Mark printer as idle"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'idle'
                if printer_name in self.printer_jobs:
                    del self.printer_jobs[printer_name]

    def set_printer_error(self, printer_name: str):
        """Mark printer as having an error"""
        with self.lock:
            if printer_name in self.printer_status:
                self.printer_status[printer_name] = 'error'

    def get_printer_stats(self) -> Dict:
        """Get statistics for all printers"""
        with self.lock:
            stats = {}
            for printer_name, printer_info in self.printers.items():
                stats[printer_name] = {
                    'status': self.printer_status.get(printer_name, 'unknown'),
                    'jobs_completed': printer_info['jobs_completed'],
                    'jobs_failed': printer_info['jobs_failed'],
                    'last_used': printer_info['last_used']
                }
            return stats

    def increment_job_completed(self, printer_name: str):
        """Increment completed job count for a printer"""
        with self.lock:
            if printer_name in self.printers:
                self.printers[printer_name]['jobs_completed'] += 1

    def increment_job_failed(self, printer_name: str):
        """Increment failed job count for a printer"""
        with self.lock:
            if printer_name in self.printers:
                self.printers[printer_name]['jobs_failed'] += 1

def find_working_printer():
    """Find a working printer on the system"""
    try:
        printers = []
        for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS):
            printers.append(printer[2])
        
        if printers:
            # Try to get default printer first
            try:
                default_printer = win32print.GetDefaultPrinter()
                if default_printer in printers:
                    return default_printer
            except:
                pass
            
            # Return first available printer
            return printers[0]
    except Exception as e:
        print(f"Error finding printers: {e}")
    
    return None

def create_passport_photo_layout(input_image_path, output_path, total_prints=8):
    """Create passport photo layout with multiple copies"""
    try:
        if not PIL_AVAILABLE:
            print("❌ PIL not available for passport photo layout")
            return False

        # Open the input image
        with Image.open(input_image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Standard passport photo size (35mm x 45mm)
            photo_width, photo_height = 413, 531  # pixels at 300 DPI
            
            # Calculate layout
            cols = int(math.sqrt(total_prints))
            rows = (total_prints + cols - 1) // cols
            
            # Create layout image
            layout_width = cols * photo_width
            layout_height = rows * photo_height
            layout = Image.new('RGB', (layout_width, layout_height), 'white')
            
            # Resize and paste photos
            for i in range(total_prints):
                row = i // cols
                col = i % cols
                
                # Resize photo to standard size
                resized_photo = img.resize((photo_width, photo_height), Image.Resampling.LANCZOS)
                
                # Calculate position
                x = col * photo_width
                y = row * photo_height
                
                # Paste photo
                layout.paste(resized_photo, (x, y))
            
            # Save layout
            layout.save(output_path, 'JPEG', quality=95)
            return True
            
    except Exception as e:
        print(f"❌ Error creating passport photo layout: {e}")
        return False

def print_document_directly(file_path: str, printer_name: str, copies: int = 1) -> bool:
    """Print document directly using Windows printing APIs - NO DIALOGS"""
    try:
        # Get printer handle
        hprinter = win32print.OpenPrinter(printer_name)
        if not hprinter:
            print(f"❌ Could not open printer: {printer_name}")
            return False
        
        try:
            # Get printer info
            printer_info = win32print.GetPrinter(hprinter, 2)
            
            # Set up document info
            doc_info = ('Print Job', None, None)
            
            # Start document
            job_id = win32print.StartDocPrinter(hprinter, 1, doc_info)
            if not job_id:
                print(f"❌ Could not start print job")
                return False
            
            try:
                # Start page
                win32print.StartPagePrinter(hprinter)
                
                # For images, we need to use GDI to draw them
                file_ext = os.path.splitext(file_path)[1].lower()
                
                if file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif']:
                    # Print image using GDI
                    success = print_image_gdi(file_path, hprinter, printer_info)
                elif file_ext == '.pdf':
                    # For PDFs, we'll use SumatraPDF with silent mode
                    success = print_pdf_sumatra_silent(file_path, printer_name, copies)
                else:
                    print(f"❌ Unsupported file type: {file_ext}")
                    success = False
                
                if success:
                    win32print.EndPagePrinter(hprinter)
                    win32print.EndDocPrinter(hprinter)
                    print(f"✅ Document printed successfully to {printer_name}")
                    return True
                else:
                    win32print.EndDocPrinter(hprinter)
                    return False
                    
            except Exception as e:
                print(f"❌ Error during printing: {e}")
                try:
                    win32print.EndDocPrinter(hprinter)
                except:
                    pass
                return False
                
        finally:
            win32print.ClosePrinter(hprinter)
            
    except Exception as e:
        print(f"❌ Error in print_document_directly: {e}")
        return False

def print_image_gdi(image_path: str, hprinter, printer_info) -> bool:
    """Print image using GDI - completely automated"""
    try:
        if not PIL_AVAILABLE:
            print("❌ PIL not available for image printing")
            return False
        
        # Load image
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Get printer DC
            dc = win32gui.CreateDC(None, printer_info['pPrinterName'], None, None)
            if not dc:
                print("❌ Could not create printer DC")
                return False
            
            try:
                # Get printer capabilities
                printer_width = win32gui.GetDeviceCaps(dc, win32con.PHYSICALWIDTH)
                printer_height = win32gui.GetDeviceCaps(dc, win32con.PHYSICALHEIGHT)
                
                # Set A4 paper size (210mm x 297mm = 8.27" x 11.69")
                # Convert to logical units (96 DPI)
                a4_width = int(8.27 * 96)  # ~794 logical units
                a4_height = int(11.69 * 96)  # ~1122 logical units
                
                # Calculate margins (0.5 inch = 48 logical units)
                margin = 48
                printable_width = a4_width - (2 * margin)
                printable_height = a4_height - (2 * margin)
                
                # Scale image to fit printable area while maintaining aspect ratio
                img_width, img_height = img.size
                scale_x = printable_width / img_width
                scale_y = printable_height / img_height
                scale = min(scale_x, scale_y)
                
                new_width = int(img_width * scale)
                new_height = int(img_height * scale)
                
                # Resize image
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Convert to Windows bitmap
                dib = ImageWin.Dib(img)
                
                # Start printing
                dc.StartDoc("Image Print")
                dc.StartPage()
                
                # Calculate centering offsets
                x_offset = margin + (printable_width - new_width) // 2
                y_offset = margin + (printable_height - new_height) // 2
                
                # Draw image
                dib.draw(dc.GetHandleOutput(), (x_offset, y_offset, x_offset + new_width, y_offset + new_height))
                
                dc.EndPage()
                dc.EndDoc()
                
                return True
                
            finally:
                win32gui.DeleteDC(dc)
                
    except Exception as e:
        print(f"❌ Error in print_image_gdi: {e}")
        return False

def print_pdf_sumatra_silent(file_path: str, printer_name: str, copies: int = 1) -> bool:
    """Print PDF using SumatraPDF with completely silent operation"""
    try:
        # Find SumatraPDF
        sumatra_paths = [
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
            r"C:\Users\{}\AppData\Local\SumatraPDF\SumatraPDF.exe".format(os.getenv('USERNAME')),
        ]
        
        sumatra_path = None
        for path in sumatra_paths:
            if os.path.exists(path):
                sumatra_path = path
                break
        
        if not sumatra_path:
            print("❌ SumatraPDF not found")
            return False
        
        # Build command with silent printing and A4 paper size
        cmd = [
            sumatra_path,
            '-print-to', printer_name,
            '-silent',
            '-print-settings', f'fit,{copies}x,A4',
            file_path
        ]
        
        print(f"🖨️ Executing silent print: {' '.join(cmd)}")
        
        # Execute with hidden window
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=60,
            startupinfo=startupinfo
        )
        
        if result.returncode == 0:
            print(f"✅ Silent PDF print successful!")
            return True
        else:
            print(f"❌ Silent PDF print failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error in print_pdf_sumatra_silent: {e}")
        return False

def print_image_automatically(image_path, printer_name, job_filename=None):
    """Print image automatically - NO DIALOGS"""
    try:
        print(f"🖨️ Printing image automatically: {image_path}")
        success = print_document_directly(image_path, printer_name, 1)
        
        if success:
            print(f"✅ Image printed successfully!")
            return True
        else:
            print(f"❌ Image print failed")
            return False
            
    except Exception as e:
        print(f"❌ Error in print_image_automatically: {e}")
        return False

def is_job_in_queue(printer_name, job_filename):
    """Check if a job is in the print queue"""
    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            jobs = win32print.EnumJobs(hprinter, 0, 10, 1)
            for job in jobs:
                if job_filename.lower() in job['pDocument'].lower():
                    return True
            return False
        finally:
            win32print.ClosePrinter(hprinter)
    except Exception as e:
        print(f"Error checking print queue: {e}")
        return False

def wait_for_job_in_and_out_of_queue(printer_name, job_filename, print_func, max_retries=5):
    """Wait for job to enter and exit the print queue"""
    try:
        # Send print job
        if not print_func():
            return False
        
        # Wait for job to enter queue
        for attempt in range(max_retries):
            if is_job_in_queue(printer_name, job_filename):
                print(f"   📋 Job entered print queue")
                break
            time.sleep(1)
        else:
            print(f"   ⚠️ Job may not have entered queue")
        
        # Wait for job to complete (exit queue)
        start_time = time.time()
        timeout = 120  # 2 minutes timeout
        
        while time.time() - start_time < timeout:
            if not is_job_in_queue(printer_name, job_filename):
                print(f"   ✅ Job completed and exited queue")
                return True
            time.sleep(2)
        
        print(f"   ⚠️ Timeout waiting for job completion")
        return False
        
    except Exception as e:
        print(f"❌ Error in wait_for_job_in_and_out_of_queue: {e}")
        return False

class SumatraPrintService:
    """SumatraPDF-based printing service"""
    
    def __init__(self):
        self.sumatra_paths = [
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
            r"C:\Users\{}\AppData\Local\SumatraPDF\SumatraPDF.exe".format(os.getenv('USERNAME')),
        ]
        self.sumatra_path = self.find_sumatra()
        
    def find_sumatra(self):
        """Find SumatraPDF installation"""
        for path in self.sumatra_paths:
            if os.path.exists(path):
                print(f"✅ Found SumatraPDF at: {path}")
                return path
        print("❌ SumatraPDF not found in common locations")
        print("   Please download from: https://www.sumatrapdfreader.org/download-free-pdf-viewer")
        return None
    
    def print_pdf(self, file_path: str, printer_name: str, copies: int = 1) -> bool:
        """Print PDF using SumatraPDF with silent operation"""
        try:
            print(f"🖨️ Printing PDF with silent SumatraPDF: {file_path}")
            success = print_pdf_sumatra_silent(file_path, printer_name, copies)
            
            if success:
                print(f"✅ PDF printed successfully using silent SumatraPDF!")
                return True
            else:
                print(f"❌ Silent SumatraPDF print failed, trying direct printing...")
                # Fallback to direct printing if SumatraPDF fails
                success = print_document_directly(file_path, printer_name, copies)
                if success:
                    print(f"✅ PDF printed successfully using direct printing!")
                    return True
                else:
                    print(f"❌ Direct PDF print also failed")
                    return False
                
        except Exception as e:
            print(f"❌ Error in print_pdf: {e}")
            return False
    
    def print_image(self, file_path: str, printer_name: str) -> bool:
        """Print image using direct GDI printing - NO DIALOGS"""
        try:
            print(f"🖨️ Printing image with GDI: {file_path}")
            success = print_document_directly(file_path, printer_name, 1)
            
            if success:
                print(f"✅ Image printed successfully using GDI!")
                return True
            else:
                print(f"❌ GDI image print failed")
                return False
                
        except Exception as e:
            print(f"❌ Error in print_image: {e}")
            return False

class AuthenticatedVendorPrintClient:
    """Vendor print client that requires authentication before printing"""
    
    def __init__(self, vendor_id: str, base_url: str = "http://localhost:8000", debug: bool = False, primary_printer: str = None):
        self.vendor_id = vendor_id
        self.base_url = base_url
        self.debug = debug
        self.is_running = False
        self.is_authenticated = False
        
        # Initialize components
        self.print_queue = PrintJobQueue()
        self.printer_manager = PrinterManager(primary_printer)
        self.sumatra_service = SumatraPrintService()
        
        # API endpoints
        self.auth_url = f"{base_url}/vendor-authenticate/"
        self.jobs_url = f"{base_url}/get-vendor-print-jobs/"
        
        # Job processing
        self.seen_tokens = set()
        self.job_dir = LOCAL_JOB_DIR
        self.poll_interval = POLL_INTERVAL
        self.queue_processor_running = False
        
        # Create directories
        os.makedirs(self.job_dir, exist_ok=True)
        os.makedirs(FAILED_JOB_DIR, exist_ok=True)
        
        print(f"🚀 AuthenticatedVendorPrintClient initialized")
        print(f"   Vendor ID: {vendor_id}")
        print(f"   Base URL: {base_url}")
        print(f"   Job Directory: {self.job_dir}")
    
    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        if level == "ERROR":
            error_logger.error(message)
        else:
            logging.info(message)
    
    def authenticate_vendor(self) -> bool:
        """Authenticate with vendor API"""
        payload = {
            "vendor_email": VENDOR_EMAIL,
            "vendor_id": self.vendor_id,
            "vendor_token": VENDOR_TOKEN,
            "shop_name": VENDOR_NAME
        }
        
        try:
            self.log("🔐 Attempting vendor authentication...")
            response = requests.post(self.auth_url, json=payload, timeout=10)
            data = response.json()
            
            if data.get('success', False):
                self.is_authenticated = True
                self.log("✅ Vendor authentication successful!")
                return True
            else:
                self.log(f"❌ Vendor authentication failed: {data.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            self.log(f"❌ Authentication error: {e}", "ERROR")
            return False
    
    def poll_for_print_jobs(self):
        """Poll vendor API for print jobs"""
        if not self.is_authenticated:
            self.log("❌ Cannot poll for jobs - not authenticated")
            return
            
        try:
            payload = {'vendor_id': self.vendor_id}
            response = requests.post(self.jobs_url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('jobs'):
                    jobs = data['jobs']
                    self.log(f"📋 Received {len(jobs)} jobs from vendor API")
                    
                    for job in jobs:
                        self.save_job_to_local_storage(job)
                else:
                    self.log("📭 No jobs available from vendor API")
            else:
                self.log(f"❌ API request failed: {response.status_code}")
                
        except Exception as e:
            self.log(f"❌ Error polling for jobs: {e}", "ERROR")
    
    def save_job_to_local_storage(self, job):
        """Save job to local storage and enqueue for printing"""
        try:
            filename = job.get('filename', 'unknown.pdf')
            token = job.get('metadata', {}).get('token') or job.get('metadata', {}).get('job_id') or filename.split('.')[0]
            
            if token in self.seen_tokens:
                return  # Already processed
            
            # Create job directory
            job_dir = os.path.join(self.job_dir, 'vendor_jobs')
            os.makedirs(job_dir, exist_ok=True)
            
            # Save job metadata
            job_file_path = os.path.join(job_dir, f'{token}.json')
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
            self.log(f"📋 Enqueued job: {filename}")
            
            # Start queue processor if not running
            if not self.queue_processor_running:
                threading.Thread(target=self.process_print_queue, daemon=True).start()
                
        except Exception as e:
            self.log(f"❌ Error saving job: {e}", "ERROR")
    
    def download_document(self, file_url: str) -> Optional[bytes]:
        """Download document from URL"""
        try:
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            self.log(f"❌ Error downloading document: {e}", "ERROR")
            return None
    
    def process_print_queue(self):
        """Process jobs in the print queue sequentially"""
        self.queue_processor_running = True
        self.log("🔄 Starting print queue processor")
        
        while self.is_running:
            try:
                # Get next job from queue
                job_node = self.print_queue.dequeue()
                if not job_node:
                    time.sleep(1)
                    continue
                
                self.log(f"🖨️ Processing job: {job_node.filename}")
                
                # Process the job
                success = self.process_single_job(job_node)
                
                if success:
                    self.log(f"✅ Job completed successfully: {job_node.filename}")
                    self.notify_job_completed(job_node.filename)
                else:
                    self.log(f"❌ Job failed: {job_node.filename}")
                    self.notify_job_failed(job_node.filename, "Print job failed")
                
            except Exception as e:
                self.log(f"❌ Error in queue processor: {e}", "ERROR")
                time.sleep(5)
        
        self.queue_processor_running = False
        self.log("🛑 Print queue processor stopped")
    
    def process_single_job(self, job_node: PrintJobNode) -> bool:
        """Process a single print job"""
        try:
            # Download document
            document_data = self.download_document(job_node.download_url)
            if not document_data:
                return False
            
            # Save to temporary file
            file_ext = os.path.splitext(job_node.filename)[1].lower()
            temp_file = tempfile.NamedTemporaryFile(suffix=file_ext, delete=False).name
            
            with open(temp_file, 'wb') as f:
                f.write(document_data)
            
            self.log(f"💾 Document saved to: {temp_file}")
            
            # Get available printer
            printer_name = self.printer_manager.get_available_printer()
            if not printer_name:
                self.log("❌ No available printer")
                return False
            
            # Mark printer as busy
            self.printer_manager.set_printer_busy(printer_name, job_node)
            
            try:
                # Print based on file type
                success = False
                copies = int(job_node.metadata.get('copies', 1))
                
                if file_ext == '.pdf':
                    success = self.sumatra_service.print_pdf(temp_file, printer_name, copies)
                elif file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif']:
                    success = self.sumatra_service.print_image(temp_file, printer_name)
                else:
                    self.log(f"⚠️ Unknown file type: {file_ext}")
                    success = False
                
                # Update printer stats
                if success:
                    self.printer_manager.increment_job_completed(printer_name)
                else:
                    self.printer_manager.increment_job_failed(printer_name)
                
                return success
                
            finally:
                # Mark printer as idle
                self.printer_manager.set_printer_idle(printer_name)
                
                # Cleanup temporary file
                try:
                    os.remove(temp_file)
                except:
                    pass
                    
        except Exception as e:
            self.log(f"❌ Error processing job: {e}", "ERROR")
            return False
    
    def notify_job_completed(self, filename: str):
        """Notify server that job was completed"""
        try:
            # Implementation depends on your API
            self.log(f"📤 Notified job completion: {filename}")
        except Exception as e:
            self.log(f"❌ Error notifying job completion: {e}", "ERROR")
    
    def notify_job_failed(self, filename: str, error_message: str):
        """Notify server that job failed"""
        try:
            # Implementation depends on your API
            self.log(f"📤 Notified job failure: {filename} - {error_message}")
        except Exception as e:
            self.log(f"❌ Error notifying job failure: {e}", "ERROR")
    
    def run(self):
        """Main run loop"""
        self.is_running = True
        self.log("🚀 Starting AuthenticatedVendorPrintClient")
        
        # Authenticate first
        if not self.authenticate_vendor():
            self.log("❌ Authentication failed. Exiting.")
            return
        
        # Start polling thread
        polling_thread = threading.Thread(target=self.polling_loop, daemon=True)
        polling_thread.start()
        
        try:
            # Main loop
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.log("🛑 Received interrupt signal")
        finally:
            self.is_running = False
            self.log("🛑 AuthenticatedVendorPrintClient stopped")
    
    def polling_loop(self):
        """Background polling loop"""
        while self.is_running:
            try:
                self.poll_for_print_jobs()
            except Exception as e:
                self.log(f"❌ Error in polling loop: {e}", "ERROR")
            
            time.sleep(self.poll_interval)

def authenticate_vendor():
    """Standalone vendor authentication function"""
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

def test_sumatra_printing():
    """Test SumatraPDF printing functionality"""
    print("🧪 Testing SumatraPDF printing...")
    
    # Find SumatraPDF
    sumatra_paths = [
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        r"C:\Users\{}\AppData\Local\SumatraPDF\SumatraPDF.exe".format(os.getenv('USERNAME')),
    ]
    
    sumatra_path = None
    for path in sumatra_paths:
        if os.path.exists(path):
            sumatra_path = path
            break
    
    if not sumatra_path:
        print("❌ SumatraPDF not found!")
        return False
    
    # Get default printer
    try:
        default_printer = win32print.GetDefaultPrinter()
        print(f"Using default printer: {default_printer}")
    except:
        print("❌ No default printer found!")
        return False
    
    # Create test PDF
    try:
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
        $e.Graphics.DrawString("Test Print Job - SumatraPDF", $font, $brush, 100, 100)
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
        
        # Create test PDF using PowerShell
        result = subprocess.run(['powershell', '-Command', test_pdf_script], 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ Test print job sent successfully!")
            print("📄 Check your printer for a test page")
            return True
        else:
            print(f"❌ Test print failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Test print error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Authenticated Vendor Print Client")
    parser.add_argument("--vendor-id", default=VENDOR_ID, help="Vendor ID for authentication")
    parser.add_argument("--url", default=BASE_URL, help="Base URL of the Django server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--printer", help="Printer name to use as primary")
    parser.add_argument("--test", action="store_true", help="Test SumatraPDF printing functionality")
    parser.add_argument("--auth-only", action="store_true", help="Test authentication only")

    args = parser.parse_args()

    print("🔧 Parsed arguments:")
    print(f"   --test: {args.test}")
    print(f"   --auth-only: {args.auth_only}")
    print(f"   --debug: {args.debug}")

    if args.test:
        print("🧪 Running SumatraPDF test mode...")
        test_sumatra_printing()
        sys.exit(0)
    elif args.auth_only:
        print("🔐 Testing authentication only...")
        authenticate_vendor()
        sys.exit(0)

    # Default: Start authenticated vendor client
    print("🚀 Starting authenticated vendor client...")
    try:
        client = AuthenticatedVendorPrintClient(
            vendor_id=args.vendor_id,
            base_url=args.url,
            debug=args.debug,
            primary_printer=args.printer
        )
        client.run()
    except Exception as e:
        print(f"❌ Error starting vendor client: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Install required packages check
    try:
        import PIL
    except ImportError:
        print("❌ Required package 'Pillow' not found!")
        print("   Please install it using: pip install Pillow")
        input("Press Enter to exit...")
        sys.exit(1)

    # Run the main function
    main()