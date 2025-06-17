
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
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

# Platform-specific printer imports
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
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
    def __init__(self, vendor_id: str, base_url: str = "ws://127.0.0.1:5000", debug: bool = False):
        """
        Initialize the automated vendor print client.
        
        Args:
            vendor_id: Vendor ID for identification
            base_url: Base WebSocket URL of the Django application
            debug: Enable debug logging
        """
        self.vendor_id = vendor_id
        self.base_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        self.debug = debug
        self.ws = None
        self.is_running = True
        self.job_queue = []
        self.processing_job = False
        
        self.log("🚀 Automated Vendor Print Client initialized")
        if self.debug:
            self.log(f"📍 Base URL: {self.base_url}")
            self.log(f"🔑 Using Vendor ID: {self.vendor_id}")
    
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
                    self.log(f"📋 Received print job: {job['filename']}")
                    self.job_queue.append(job)
                    
                    # Start processing if not already processing
                    if not self.processing_job:
                        threading.Thread(target=self.process_job_queue, daemon=True).start()
                        
            elif message_type == 'print_jobs_response':
                jobs = data.get('jobs', [])
                if jobs:
                    self.log(f"📋 Received {len(jobs)} print jobs")
                    self.job_queue.extend(jobs)
                    
                    if not self.processing_job:
                        threading.Thread(target=self.process_job_queue, daemon=True).start()
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
    
    def job_request_loop(self):
        """Continuously request print jobs every 30 seconds."""
        while self.is_running and self.ws and self.ws.sock:
            try:
                # Request print jobs
                self.ws.send(json.dumps({
                    'type': 'request_print_jobs',
                    'vendor_id': self.vendor_id
                }))
                
                # Wait 30 seconds before next request
                time.sleep(30)
                
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
        """Process a single print job automatically."""
        filename = job.get('filename', 'unknown')
        download_url = job.get('download_url', '')
        metadata = job.get('metadata', {})
        
        self.log(f"🔄 Processing job: {filename}")
        
        # Check if printer is available
        printer_available, printer_name = self.is_printer_available()
        
        if not printer_available:
            error_msg = "No printer detected on this system"
            self.log(f"🖨️  {error_msg}")
            self.notify_job_failed(filename, error_msg)
            return False
        
        # Download document
        document_data = self.download_document(download_url)
        if not document_data:
            error_msg = "Failed to download document"
            self.notify_job_failed(filename, error_msg)
            return False
        
        # Apply print settings from metadata
        print_settings = self.prepare_print_settings(metadata)
        
        # Print document
        print_success = self.print_document_with_settings(
            document_data, printer_name, filename, print_settings
        )
        
        # Notify completion
        if print_success:
            self.notify_job_completed(filename)
        else:
            self.notify_job_failed(filename, "Printing failed")
        
        return print_success
    
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
        """Print document with specific settings."""
        try:
            copies = print_settings.get('copies', 1)
            self.log(f"🖨️  Printing {filename} ({copies} copies) to {printer_name}")
            self.log(f"📋 Settings: {print_settings}")
            
            if PLATFORM_PRINTING == "windows":
                return self._print_windows_with_settings(
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
    
    def _print_windows_with_settings(self, document_data: bytes, printer_name: str, 
                                   filename: str, print_settings: Dict) -> bool:
        """Print document on Windows with settings."""
        try:
            job_name = f"AutoPrint: {filename}"
            copies = print_settings.get('copies', 1)
            
            # Open printer
            printer_handle = win32print.OpenPrinter(printer_name)
            
            try:
                # For each copy
                for copy_num in range(copies):
                    # Start print job
                    job_id = win32print.StartDocPrinter(printer_handle, 1, (f"{job_name} (Copy {copy_num + 1})", None, "RAW"))
                    win32print.StartPagePrinter(printer_handle)
                    
                    # Send document data
                    win32print.WritePrinter(printer_handle, document_data)
                    
                    win32print.EndPagePrinter(printer_handle)
                    win32print.EndDocPrinter(printer_handle)
                    
                    self.log(f"✅ Copy {copy_num + 1}/{copies} sent (Job ID: {job_id})")
                
                return True
                
            finally:
                win32print.ClosePrinter(printer_handle)
                
        except Exception as e:
            self.log(f"❌ Windows printing error: {str(e)}")
            return False
    
    def _print_cups_with_settings(self, document_data: bytes, printer_name: str, 
                                filename: str, print_settings: Dict) -> bool:
        """Print document on Linux/Mac using CUPS with settings."""
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
            
            self.log(f"✅ Print job sent successfully (Job ID: {job_id})")
            return True
            
        except Exception as e:
            self.log(f"❌ CUPS printing error: {str(e)}")
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
    parser.add_argument("--url", default="ws://127.0.0.1:5000", help="Base WebSocket URL of the Django application")
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
