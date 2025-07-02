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
    import win32print
    printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    hp_printers = [p[2] for p in printers if 'HP' in p[2].upper()]
    hp_printers.sort(key=lambda x: ('Copy' in x, x))
    for printer_name in hp_printers:
        try:
            handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(handle, 2)
            win32print.ClosePrinter(handle)
            if info['Status'] == 0:
                return printer_name
        except:
            continue
    for p in printers:
        printer_name = p[2]
        if 'PDF' not in printer_name.upper():
            try:
                handle = win32print.OpenPrinter(printer_name)
                info = win32print.GetPrinter(handle, 2)
                win32print.ClosePrinter(handle)
                if info['Status'] == 0:
                    return printer_name
            except:
                continue
    return None

def print_image_automatically(image_path, printer_name):
    import subprocess, win32api
    # Method 1: PowerShell
    ps_script = f'''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing
try {{
    $image = [System.Drawing.Image]::FromFile("{image_path}")
    $printDoc = New-Object System.Drawing.Printing.PrintDocument
    $printDoc.PrinterSettings.PrinterName = "{printer_name}"
    $printDoc.DefaultPageSettings.Color = $true
    $printDoc.DefaultPageSettings.Landscape = $false
    foreach ($paperSize in $printDoc.PrinterSettings.PaperSizes) {{
        if ($paperSize.PaperName -eq "A4") {{
            $printDoc.DefaultPageSettings.PaperSize = $paperSize
            break
        }}
    }}
    $printPage = {{
        param($sender, $e)
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
    }}
    $printDoc.add_PrintPage($printPage)
    $printDoc.Print()
    $image.Dispose()
    exit 0
}} catch {{
    exit 1
}}
'''
    result = subprocess.run(['powershell', '-Command', ps_script], capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return True
    # Method 2: Windows Photo Viewer
    try:
        cmd = [
            'rundll32.exe',
            'C:\\Windows\\System32\\shimgvw.dll,ImageView_PrintTo',
            image_path,
            printer_name
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True
    except Exception:
        pass
    # Method 3: ShellExecute
    try:
        win32api.ShellExecute(0, "print", image_path, None, ".", 0)
        return True
    except Exception:
        pass
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
        """Main queue processor that handles jobs efficiently"""
        self.queue_processor_running = True
        self.log("🔄 Starting print queue processor")

        try:
            while self.is_running and (not self.print_queue.is_empty() or not self.failed_jobs_queue.is_empty()):
                # Process failed jobs first (priority)
                if not self.failed_jobs_queue.is_empty():
                    job_node = self.failed_jobs_queue.dequeue()
                    if job_node:
                        self.debug_log(f"🔄 Processing priority failed job: {job_node.filename}")
                        self.process_single_job_async(job_node, priority=True)

                # Process regular jobs
                elif not self.print_queue.is_empty():
                    job_node = self.print_queue.dequeue()
                    if job_node:
                        self.process_single_job_async(job_node)

                # Small delay to prevent overwhelming
                time.sleep(0.1)

        except Exception as e:
            self.log(f"❌ Error in queue processor: {str(e)}")
        finally:
            self.queue_processor_running = False
            self.log("⏹️ Print queue processor stopped")

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

        try:
            self.log(f"🖨️ Processing {job_node.filename} on {printer_name} (Attempt {job_node.attempts + 1})")

            # Create checkpoint for resume capability
            checkpoint_file = self._create_job_checkpoint(job_node, printer_name)

            # Check if printer is actually available
            if not self.is_specific_printer_available(printer_name):
                self.log(f"🖨️ Printer {printer_name} not available")
                self.printer_manager.set_printer_error(printer_name)
                return False

            job_node.attempts += 1

            # Check for resume from checkpoint
            resume_data = self._check_resume_checkpoint(job_node.filename)
            if resume_data:
                self.log(f"🔄 Resuming job from checkpoint: {job_node.filename}")
                document_data = resume_data.get('document_data')
                print_settings = resume_data.get('print_settings')
            else:
                # Download document
                document_data = self.download_document(job_node.download_url)
                if not document_data:
                    self.log(f"❌ Failed to download document: {job_node.filename}")
                    return False

            # Prepare print settings
            print_settings = self.prepare_print_settings(job_node.metadata)
            
            # Save checkpoint with document data
            self._save_job_checkpoint(job_node, printer_name, document_data, print_settings)

            # Print document with interrupt handling
            print_success = self._print_with_interrupt_handling(
                document_data, printer_name, job_node.filename, print_settings, job_node
            )

            if print_success:
                # Update metrics
                processing_time = time.time() - start_time
                self.job_metrics['processing_times'].append(processing_time)
                self.job_metrics['total_completed'] += 1

                # Calculate average processing time
                if self.job_metrics['processing_times']:
                    self.job_metrics['average_processing_time'] = sum(self.job_metrics['processing_times']) / len(self.job_metrics['processing_times'])

                # Update printer stats
                self.printer_manager.increment_job_completed(printer_name)

                # Clean up checkpoint
                self._cleanup_job_checkpoint(job_node.filename)

                self.log(f"✅ Successfully completed job: {job_node.filename} ({processing_time:.2f}s)")
                return True
            else:
                self.printer_manager.increment_job_failed(printer_name)
                return False

        except KeyboardInterrupt:
            self.log(f"⚠️ Job interrupted by user: {job_node.filename}")
            self._save_interrupt_checkpoint(job_node, printer_name)
            return False
        except Exception as e:
            self.log(f"❌ Error processing job {job_node.filename}: {str(e)}")
            return False
        finally:
            # Cleanup temporary files
            if checkpoint_file and os.path.exists(checkpoint_file):
                try:
                    os.remove(checkpoint_file)
                except:
                    pass

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
            'color': metadata.get('color', 'bw'),
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

    def print_document_with_settings(self, document_data: bytes, printer_name: str, 
                                   filename: str, print_settings: Dict) -> bool:
        """Print document with specific settings using secure printing."""
        try:
            copies = print_settings.get('copies', 1)
            self.log(f"🖨️  Printing {filename} ({copies} copies) to {printer_name}")
            self.log(f"📋 Settings: {print_settings}")

            file_extension = filename.lower().split('.')[-1]
            temp_fd, temp_path = tempfile.mkstemp(suffix=f'.{file_extension}', prefix='secure_print_')
            try:
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(document_data)
                # Auto-select printer if not available
                if not printer_name or not self.is_specific_printer_available(printer_name):
                    self.log(f"🔍 Printer '{printer_name}' not available, auto-selecting working printer...")
                    printer_name = find_working_printer()
                    if not printer_name:
                        self.log("❌ No working printer found!")
                        return False
                    self.log(f"🎯 Using printer: {printer_name}")
                # Image printing
                if file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
                    return print_image_automatically(temp_path, printer_name)
                # PDF printing (use robust PDF print logic)
                elif file_extension == 'pdf':
                    # Try Adobe, Sumatra, PowerShell, fallback to ShellExecute
                    if self._secure_print_pdf(temp_path, printer_name, copies, print_settings.get('color', 'bw') == 'color'):
                        return True
                    else:
                        self.log("❌ All PDF printing methods failed")
                        return False
                # Word/text files
                elif file_extension in ['doc', 'docx', 'txt', 'rtf']:
                    return self._secure_print_document(temp_path, printer_name, copies)
                # Generic
                else:
                    return self._secure_print_generic(temp_path, printer_name, copies)
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
        except Exception as e:
            self.log(f"❌ Printing failed: {str(e)}")
            return False

    def _secure_print_pdf(self, file_path: str, printer_name: str, copies: int, color: bool) -> bool:
        """Adobe-focused PDF printing with enhanced reliability."""
        try:
            self.log(f"🔍 Starting Adobe-focused PDF printing ({copies} copies)")

            # Primary Method: Adobe Reader/Acrobat (Enhanced)
            if self._try_adobe_print(file_path, printer_name, copies):
                self.log("✅ PDF printed successfully using Adobe")
                return True

            # Fallback Method 1: SumatraPDF
            self.log("🔄 Adobe failed, trying SumatraPDF fallback...")
            if self._try_sumatra_print(file_path, printer_name, copies):
                self.log("✅ PDF printed using SumatraPDF fallback")
                return True

            # Fallback Method 2: PowerShell PDF printing
            self.log("🔄 SumatraPDF failed, trying PowerShell fallback...")
            if self._try_powershell_pdf_print(file_path, printer_name, copies, color):
                self.log("✅ PDF printed using PowerShell fallback")
                return True

            # Fallback Method 3: Windows default PDF handler
            self.log("🔄 PowerShell failed, trying Windows default fallback...")
            if self._try_windows_pdf_print(file_path, printer_name, copies):
                self.log("✅ PDF printed using Windows default fallback")
                return True

            self.log("❌ All PDF printing methods failed")
            return False

        except Exception as e:
            self.log(f"❌ Adobe-focused PDF print error: {str(e)}")
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
        """Enhanced Adobe printing with synchronous operation and automatic cleanup."""
        adobe_process = None
        temp_status_file = None
        
        try:
            self.log(f"🖨️ Starting Adobe print job: {copies} copies to {printer_name}")
            
            # Adobe paths in priority order
            adobe_paths = [
                r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
                r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe", 
                r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                r"C:\Program Files (x86)\Adobe\Reader 11.0\Reader\AcroRd32.exe",
                r"C:\Program Files\Adobe\Reader 11.0\Reader\AcroRd32.exe"
            ]

            adobe_exe = None
            for path in adobe_paths:
                if os.path.exists(path):
                    adobe_exe = path
                    self.log(f"✅ Found Adobe at: {path}")
                    break

            if not adobe_exe:
                self.log("❌ Adobe Reader/Acrobat not found")
                return False

            # Create status tracking file
            temp_status_file = tempfile.mktemp(suffix='.status')
            
            # Enhanced printing with job monitoring
            success_count = 0
            
            for copy_num in range(copies):
                self.log(f"🖨️ Printing copy {copy_num + 1}/{copies}")
                
                # Start Adobe with print command
                cmd = [adobe_exe, "/t", file_path, f'"{printer_name}"']
                
                try:
                    # Start Adobe process
                    adobe_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    # Monitor Adobe process with timeout
                    start_time = time.time()
                    timeout = 120  # 2 minutes per copy
                    
                    while adobe_process.poll() is None:
                        if time.time() - start_time > timeout:
                            self.log(f"⏰ Adobe process timeout for copy {copy_num + 1}")
                            adobe_process.terminate()
                            time.sleep(2)
                            if adobe_process.poll() is None:
                                adobe_process.kill()
                            break
                        time.sleep(1)
                    
                    # Check if process completed successfully
                    return_code = adobe_process.returncode
                    
                    if return_code == 0:
                        success_count += 1
                        self.log(f"✅ Copy {copy_num + 1} sent to printer successfully")
                        
                        # Wait for print job to be processed by printer
                        self._wait_for_printer_processing(printer_name)
                        
                    else:
                        self.log(f"❌ Copy {copy_num + 1} failed with return code: {return_code}")
                        
                        # Try to recover from error
                        if copy_num < copies - 1:  # Not the last copy
                            self.log("🔄 Attempting recovery for next copy...")
                            self._cleanup_adobe_processes()
                            time.sleep(3)
                    
                    # Small delay between copies
                    if copy_num < copies - 1:
                        time.sleep(2)
                        
                except subprocess.TimeoutExpired:
                    self.log(f"⏰ Adobe process timed out for copy {copy_num + 1}")
                    if adobe_process:
                        adobe_process.kill()
                    
                except Exception as copy_error:
                    self.log(f"❌ Error printing copy {copy_num + 1}: {str(copy_error)}")
                    
                finally:
                    # Cleanup Adobe process for this copy
                    if adobe_process and adobe_process.poll() is None:
                        try:
                            adobe_process.terminate()
                            time.sleep(1)
                            if adobe_process.poll() is None:
                                adobe_process.kill()
                        except:
                            pass

            # Final cleanup of all Adobe processes
            self._cleanup_adobe_processes()
            
            # Check overall success
            if success_count == copies:
                self.log(f"✅ All {copies} copies printed successfully via Adobe")
                return True
            elif success_count > 0:
                self.log(f"⚠️ Partial success: {success_count}/{copies} copies printed")
                return success_count >= (copies // 2)  # Consider success if more than half printed
            else:
                self.log(f"❌ Adobe printing failed for all copies")
                return False

        except Exception as e:
            self.log(f"❌ Adobe printing error: {str(e)}")
            return False
            
        finally:
            # Final cleanup
            if adobe_process and adobe_process.poll() is None:
                try:
                    adobe_process.terminate()
                    time.sleep(1)
                    if adobe_process.poll() is None:
                        adobe_process.kill()
                except:
                    pass
            
            # Cleanup status file
            if temp_status_file and os.path.exists(temp_status_file):
                try:
                    os.remove(temp_status_file)
                except:
                    pass
            
            # Final Adobe cleanup
            self._cleanup_adobe_processes()

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

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Enhanced Automated Vendor Print Client")
    parser.add_argument("--vendor-id", required=True, help="Vendor ID for identification")
    parser.add_argument("--url", default="ws://localhost:8000", help="Base WebSocket URL of the Django application")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--printer", help="Printer name to use as primary")

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
        debug=args.debug,
        primary_printer=args.printer
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