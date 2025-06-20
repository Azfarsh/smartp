
#!/usr/bin/env python3
"""
Automated Vendor Print Client Script
====================================
Continuously monitors for print jobs via WebSocket and handles automatic printing.
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
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

# Additional imports for Windows printing
try:
    from PIL import Image, ImageWin
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

class AutomatedVendorPrintClient:
    def __init__(self, vendor_id: str, base_url: str = "ws://localhost:5000", debug: bool = False):
        """
        Initialize the automated vendor print client.
        
        Args:
            vendor_id: Vendor ID for identification
            base_url: Base WebSocket URL of the Django application
            debug: Enable debug logging
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
        self.job_queue = []
        self.processing_job = False
        
        # Enhanced job tracking
        self.processed_jobs = set()  # Cache of completed job filenames
        self.job_execution_array = []  # Array to track job executions
        self.job_lock = threading.Lock()  # Thread safety for job processing
        
        self.log("🚀 Automated Vendor Print Client initialized")
        if self.debug:
            self.log(f"📍 Base URL: {self.base_url}")
            self.log(f"🔑 Using Vendor ID: {self.vendor_id}")
            self.log("📊 Job execution tracking enabled")
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
    
    def debug_log(self, message: str):
        """Log debug messages only if debug mode is enabled."""
        if self.debug:
            self.log(message, "DEBUG")
    
    def on_message(self, ws, message):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            if message_type == 'print_job':
                # Received a new print job
                job = data.get('job')
                if job:
                    filename = job['filename']
                    
                    # Check if job was already processed
                    with self.job_lock:
                        if filename in self.processed_jobs:
                            self.debug_log(f"🔄 Skipping already processed job: {filename}")
                            return
                        
                        # Add to processed set immediately to prevent duplicates
                        self.processed_jobs.add(filename)
                    
                    self.log(f"📋 Received print job: {filename}")
                    self.job_queue.append(job)
                    
                    # Start processing if not already processing
                    if not self.processing_job:
                        threading.Thread(target=self.process_job_queue, daemon=True).start()
                        
            elif message_type == 'print_jobs_response':
                jobs = data.get('jobs', [])
                if jobs:
                    # Filter out already processed jobs
                    new_jobs = []
                    with self.job_lock:
                        for job in jobs:
                            filename = job['filename']
                            if filename not in self.processed_jobs:
                                self.processed_jobs.add(filename)
                                new_jobs.append(job)
                            else:
                                self.debug_log(f"🔄 Skipping already processed job: {filename}")
                    
                    if new_jobs:
                        self.log(f"📋 Received {len(new_jobs)} new print jobs (filtered {len(jobs) - len(new_jobs)} duplicates)")
                        self.job_queue.extend(new_jobs)
                        
                        if not self.processing_job:
                            threading.Thread(target=self.process_job_queue, daemon=True).start()
                    else:
                        self.debug_log("📭 No new print jobs (all were duplicates)")
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
                # Only request if not currently processing jobs
                if not self.processing_job and len(self.job_queue) == 0:
                    self.debug_log("📤 Requesting new print jobs...")
                    self.ws.send(json.dumps({
                        'type': 'request_print_jobs',
                        'vendor_id': self.vendor_id
                    }))
                else:
                    self.debug_log("⏳ Skipping job request - currently processing or queue not empty")
                
                # Log job execution summary every 10 minutes
                loop_count += 1
                if loop_count % 10 == 0:  # Every 10 loops (10 minutes)
                    summary = self.get_job_execution_summary()
                    self.log(f"📊 Job Summary: {summary['completed']}/{summary['total']} completed " +
                           f"({summary['success_rate']:.1f}% success rate)")
                    
                    # Cleanup old entries every hour
                    if loop_count % 60 == 0:  # Every 60 loops (1 hour)
                        self.cleanup_old_job_entries()
                
                # Wait 60 seconds before next request (reduced frequency)
                time.sleep(60)
                
            except Exception as e:
                self.log(f"❌ Error in job request loop: {str(e)}")
                break
    
    def process_job_queue(self):
        """Process all jobs in the queue."""
        self.processing_job = True
        
        while self.job_queue and self.is_running:
            job = self.job_queue.pop(0)
            self.process_single_job(job)
            
            # Small delay between jobs
            time.sleep(2)
        
        self.processing_job = False
    
    def process_single_job(self, job):
        """Process a single print job automatically with enhanced tracking."""
        filename = job.get('filename', 'unknown')
        download_url = job.get('download_url', '')
        metadata = job.get('metadata', {})
        
        # Add job to execution tracking
        job_entry = {
            'filename': filename,
            'start_time': time.time(),
            'status': 'processing',
            'attempts': 1,
            'metadata': metadata
        }
        
        with self.job_lock:
            self.job_execution_array.append(job_entry)
        
        self.log(f"🔄 Processing job: {filename} (Tracked: {len(self.job_execution_array)} jobs)")
        
        try:
            # Check if printer is available
            printer_available, printer_name = self.is_printer_available()
            
            if not printer_available:
                error_msg = "No printer detected on this system"
                self.log(f"🖨️  {error_msg}")
                self._update_job_status(filename, 'failed', error_msg)
                self.notify_job_failed(filename, error_msg)
                self.remove_from_processed_cache(filename)  # Allow retry later
                return False
            
            # Update status to downloading
            self._update_job_status(filename, 'downloading')
            
            # Download document
            document_data = self.download_document(download_url)
            if not document_data:
                error_msg = "Failed to download document"
                self._update_job_status(filename, 'failed', error_msg)
                self.notify_job_failed(filename, error_msg)
                self.remove_from_processed_cache(filename)  # Allow retry later
                return False
            
            # Update status to printing
            self._update_job_status(filename, 'printing')
            
            # Apply print settings from metadata
            print_settings = self.prepare_print_settings(metadata)
            
            # Print document - ONLY notify completion if printing actually succeeds
            print_success = self.print_document_with_settings(
                document_data, printer_name, filename, print_settings
            )
            
            # Only notify completion after successful printing
            if print_success:
                # Wait a moment to ensure print job is actually sent to printer
                time.sleep(2)
                
                # Update job status to completed
                self._update_job_status(filename, 'completed')
                
                # Notify backend and update R2 storage
                self.notify_job_completed(filename)
                self.update_r2_job_status(filename, 'YES')
                
                self.log(f"✅ Successfully completed and notified job: {filename}")
                return True
            else:
                error_msg = "Printing failed - job not sent to printer"
                self.log(f"❌ {error_msg}: {filename}")
                self._update_job_status(filename, 'failed', error_msg)
                self.notify_job_failed(filename, error_msg)
                self.remove_from_processed_cache(filename)  # Allow retry later
                return False
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.log(f"❌ Error processing job {filename}: {error_msg}")
            self._update_job_status(filename, 'failed', error_msg)
            self.notify_job_failed(filename, error_msg)
            self.remove_from_processed_cache(filename)  # Allow retry later
            return False
    
    def prepare_print_settings(self, metadata):
        """Prepare print settings from metadata."""
        return {
            'copies': int(metadata.get('copies', 1)),
            'color': metadata.get('color', 'bw'),
            'orientation': metadata.get('orientation', 'portrait'),
            'page_size': metadata.get('page_size', 'A4'),
            'page_range': metadata.get('page_range', 'all'),
            'specific_pages': metadata.get('specific_pages', ''),
            'spiral_binding': metadata.get('spiral_binding', 'No'),
            'lamination': metadata.get('lamination', 'No')
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
    
    def print_document_with_settings(self, document_data: bytes, printer_name: str, 
                                   filename: str, print_settings: Dict) -> bool:
        """Print document with specific settings using secure printing."""
        try:
            copies = print_settings.get('copies', 1)
            self.log(f"🖨️  Printing {filename} ({copies} copies) to {printer_name}")
            self.log(f"📋 Settings: {print_settings}")
            
            if PLATFORM_PRINTING == "windows":
                return self._secure_print_windows(
                    document_data, printer_name, filename, print_settings
                )
            elif PLATFORM_PRINTING == "cups":
                return self._print_cups_with_settings(
                    document_data, printer_name, filename, print_settings
                )
            else:
                self.log("❌ No printing backend available")
                return False
                
        except Exception as e:
            self.log(f"❌ Printing failed: {str(e)}")
            return False
    
    def _secure_print_windows(self, document_data: bytes, printer_name: str, 
                            filename: str, print_settings: Dict) -> bool:
        """Secure Windows printing with multiple methods and cleanup."""
        temp_path = None
        try:
            copies = print_settings.get('copies', 1)
            color = print_settings.get('color', 'bw') == 'color'
            
            # Create secure temporary file
            file_extension = filename.lower().split('.')[-1] if '.' in filename else 'bin'
            temp_fd, temp_path = tempfile.mkstemp(suffix=f'.{file_extension}', prefix='secure_print_')
            
            try:
                # Write document data to temporary file
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(document_data)
                
                self.log(f"📄 Created secure temp file: {os.path.basename(temp_path)}")
                
                # Print based on file type using secure methods
                success = False
                if file_extension == 'pdf':
                    success = self._secure_print_pdf(temp_path, printer_name, copies, color)
                elif file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
                    success = self._secure_print_image(temp_path, printer_name, copies)
                elif file_extension in ['doc', 'docx', 'txt', 'rtf']:
                    success = self._secure_print_document(temp_path, printer_name, copies)
                else:
                    success = self._secure_print_generic(temp_path, printer_name, copies)
                
                if success:
                    self.log(f"✅ Print job sent successfully: {filename}")
                    # Wait for print job to be processed
                    time.sleep(3)
                    return True
                else:
                    self.log(f"❌ Failed to send print job: {filename}")
                    return False
                    
            finally:
                # Secure cleanup of temporary file
                if temp_path and os.path.exists(temp_path):
                    self._secure_delete_file(temp_path)
                
        except Exception as e:
            self.log(f"❌ Secure Windows printing error: {str(e)}")
            if temp_path and os.path.exists(temp_path):
                self._secure_delete_file(temp_path)
            return False
    
    def _secure_print_pdf(self, file_path: str, printer_name: str, copies: int, color: bool) -> bool:
        """Secure PDF printing using multiple methods."""
        try:
            self.log(f"🔍 Attempting secure PDF printing ({copies} copies)")
            
            # Method 1: Try SumatraPDF (lightweight, reliable)
            if self._try_sumatra_print(file_path, printer_name, copies):
                return True
            
            # Method 2: Try Adobe Reader
            if self._try_adobe_print(file_path, printer_name, copies):
                return True
            
            # Method 3: Try PowerShell PDF printing
            if self._try_powershell_pdf_print(file_path, printer_name, copies, color):
                return True
            
            # Method 4: Windows default PDF handler
            if self._try_windows_pdf_print(file_path, printer_name, copies):
                return True
            
            self.log("❌ All PDF printing methods failed")
            return False
            
        except Exception as e:
            self.log(f"❌ Secure PDF print error: {str(e)}")
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
        """Try printing with Adobe Reader."""
        try:
            adobe_paths = [
                r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
                r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            ]
            
            for adobe_path in adobe_paths:
                if os.path.exists(adobe_path):
                    for i in range(copies):
                        cmd = [adobe_path, "/t", file_path, printer_name]
                        result = subprocess.run(cmd, capture_output=True, timeout=60)
                        if result.returncode != 0:
                            break
                        time.sleep(2)
                    
                    if result.returncode == 0:
                        self.log("✅ PDF printed using Adobe Reader")
                        return True
            
            return False
            
        except Exception as e:
            self.debug_log(f"Adobe Reader method failed: {e}")
            return False
    
    def _try_powershell_pdf_print(self, file_path: str, printer_name: str, copies: int, color: bool) -> bool:
        """Try printing with PowerShell."""
        try:
            color_setting = "True" if color else "False"
            
            ps_script = f'''
try {{
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "{file_path}"
    $startInfo.Verb = "printto"
    $startInfo.Arguments = '"{printer_name}"'
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = "Hidden"
    
    for ($i = 0; $i -lt {copies}; $i++) {{
        $process = [System.Diagnostics.Process]::Start($startInfo)
        $process.WaitForExit(30000)
        Start-Sleep -Seconds 1
    }}
    
    Write-Host "PDF print job sent"
    exit 0
    
}} catch {{
    Write-Host "PowerShell PDF print error: $_"
    exit 1
}}
'''
            
            result = subprocess.run(['powershell', '-Command', ps_script], 
                                  capture_output=True, text=True, timeout=90)
            
            if result.returncode == 0:
                self.log("✅ PDF printed using PowerShell")
                return True
            
            return False
            
        except Exception as e:
            self.debug_log(f"PowerShell method failed: {e}")
            return False
    
    def _try_windows_pdf_print(self, file_path: str, printer_name: str, copies: int) -> bool:
        """Try printing with Windows default PDF handler."""
        try:
            for i in range(copies):
                # Try multiple Windows methods
                try:
                    result = win32api.ShellExecute(0, "printto", file_path, f'"{printer_name}"', ".", 0)
                    if result > 32:
                        time.sleep(2)
                        continue
                except:
                    pass
                
                try:
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 0)
                    if result > 32:
                        time.sleep(2)
                        continue
                except:
                    pass
                
                return False
            
            self.log("✅ PDF printed using Windows default")
            return True
            
        except Exception as e:
            self.debug_log(f"Windows PDF print failed: {e}")
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
    
    def remove_from_processed_cache(self, filename: str):
        """Remove a job from the processed cache to allow retry."""
        with self.job_lock:
            self.processed_jobs.discard(filename)
            self.debug_log(f"🗑️ Removed {filename} from processed cache for retry")
    
    def _update_job_status(self, filename: str, status: str, error_msg: str = None):
        """Update job status in the execution array."""
        with self.job_lock:
            for job in self.job_execution_array:
                if job['filename'] == filename:
                    job['status'] = status
                    job['last_update'] = time.time()
                    if error_msg:
                        job['error'] = error_msg
                    break
    
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
    
    def get_job_execution_summary(self):
        """Get summary of job executions for monitoring."""
        with self.job_lock:
            total_jobs = len(self.job_execution_array)
            completed_jobs = len([j for j in self.job_execution_array if j['status'] == 'completed'])
            failed_jobs = len([j for j in self.job_execution_array if j['status'] == 'failed'])
            processing_jobs = len([j for j in self.job_execution_array if j['status'] == 'processing'])
            
            return {
                'total': total_jobs,
                'completed': completed_jobs,
                'failed': failed_jobs,
                'processing': processing_jobs,
                'success_rate': (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0
            }
    
    def cleanup_old_job_entries(self, max_age_hours: int = 24):
        """Remove old job entries from tracking array."""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        with self.job_lock:
            original_count = len(self.job_execution_array)
            self.job_execution_array = [
                job for job in self.job_execution_array
                if (current_time - job.get('start_time', current_time)) < max_age_seconds
            ]
            cleaned_count = original_count - len(self.job_execution_array)
            
            if cleaned_count > 0:
                self.log(f"🧹 Cleaned up {cleaned_count} old job entries")
    
    def clear_processed_cache(self):
        """Clear the processed jobs cache (useful for testing)."""
        with self.job_lock:
            cleared_count = len(self.processed_jobs)
            self.processed_jobs.clear()
            self.job_execution_array.clear()
            self.log(f"🗑️ Cleared processed cache ({cleared_count} jobs) and execution array")
    
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
        self.log("🔄 Starting Automated Print Client")
        
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

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Automated Vendor Print Client")
    parser.add_argument("--vendor-id", required=True, help="Vendor ID for identification")
    parser.add_argument("--url", default="ws://localhost:5000", help="Base WebSocket URL of the Django application")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.vendor_id:
        print("❌ Error: Vendor ID is required")
        sys.exit(1)
    
    # Check platform printing support
    if PLATFORM_PRINTING is None:
        print("⚠️  Warning: No printing backend available.")
        print("   For Windows: pip install pywin32")
        print("   For Linux/Mac: pip install pycups")
        print("   Continuing in read-only mode...")
    
    # Create and run client
    client = AutomatedVendorPrintClient(
        vendor_id=args.vendor_id,
        base_url=args.url,
        debug=args.debug
    )
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"💥 Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
