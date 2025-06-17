#!/usr/bin/env python3
"""
Vendor Print Client Script
==========================
Continuously monitors for print jobs via WebSocket and handles printing without storing files locally.
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

class VendorPrintClient:
    def __init__(self, vendor_id: str, base_url: str = "ws://127.0.0.1:8000", debug: bool = False):
        """
        Initialize the vendor print client.
        
        Args:
            vendor_id: Vendor ID for identification
            base_url: Base WebSocket URL of the Django application
            debug: Enable debug logging
        """
        self.vendor_id = vendor_id
        self.base_url = base_url.rstrip('/')
        self.debug = debug
        self.ws = None
        
        self.log("🚀 Vendor Print Client initialized")
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
            
            if message_type == 'print_jobs_response':
                jobs = data.get('jobs', [])
                if jobs:
                    self.log(f"📋 Received {len(jobs)} print job(s)")
                    for job in jobs:
                        self.process_job(job)
                else:
                    self.debug_log("📭 No print jobs available")
                    
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
    
    def on_open(self, ws):
        """Handle WebSocket connection open."""
        self.log("🔌 WebSocket connection established")
        # Request print jobs
        ws.send(json.dumps({
            'type': 'request_print_jobs',
            'vendor_id': self.vendor_id
        }))
    
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
    
    def print_document(self, document_data: bytes, printer_name: str, job_info: Dict) -> bool:
        """Print document directly from memory."""
        try:
            self.log(f"🖨️  Printing job #{job_info.get('id', 'unknown')} to {printer_name}")
            
            if PLATFORM_PRINTING == "windows":
                return self._print_windows(document_data, printer_name, job_info)
            elif PLATFORM_PRINTING == "cups":
                return self._print_cups(document_data, printer_name, job_info)
            else:
                self.log("❌ No printing backend available")
                return False
                
        except Exception as e:
            self.log(f"❌ Printing failed: {str(e)}")
            return False
    
    def _print_windows(self, document_data: bytes, printer_name: str, job_info: Dict) -> bool:
        """Print document on Windows using win32print."""
        try:
            # Create a temporary file in memory
            doc_stream = io.BytesIO(document_data)
            
            job_name = f"SmartPrint Job #{job_info.get('id', 'unknown')}"
            
            # Open printer
            printer_handle = win32print.OpenPrinter(printer_name)
            
            try:
                # Start print job
                job_id = win32print.StartDocPrinter(printer_handle, 1, (job_name, None, "RAW"))
                win32print.StartPagePrinter(printer_handle)
                
                # For RAW printing, we would send the PDF data directly
                win32print.WritePrinter(printer_handle, document_data)
                
                win32print.EndPagePrinter(printer_handle)
                win32print.EndDocPrinter(printer_handle)
                
                self.log(f"✅ Print job sent successfully (Job ID: {job_id})")
                return True
                
            finally:
                win32print.ClosePrinter(printer_handle)
                
        except Exception as e:
            self.log(f"❌ Windows printing error: {str(e)}")
            return False
    
    def _print_cups(self, document_data: bytes, printer_name: str, job_info: Dict) -> bool:
        """Print document on Linux/Mac using CUPS."""
        try:
            conn = cups.Connection()
            job_name = f"SmartPrint Job #{job_info.get('id', 'unknown')}"
            
            # Create temporary file-like object
            doc_stream = io.BytesIO(document_data)
            
            # Print the document
            job_id = conn.printFile(printer_name, doc_stream, job_name, {})
            
            self.log(f"✅ Print job sent successfully (Job ID: {job_id})")
            return True
            
        except Exception as e:
            self.log(f"❌ CUPS printing error: {str(e)}")
            return False
    
    def notify_job_complete(self, job_id: int, success: bool, error_message: str = None):
        """Notify the backend that a job has been completed via WebSocket."""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                payload = {
                    'type': 'print_status',
                    'job_id': job_id,
                    'status': 'completed' if success else 'failed',
                    'printed_successfully': success
                }
                
                if error_message:
                    payload['error_message'] = error_message
                
                self.debug_log(f"📤 Notifying job completion: {payload}")
                self.ws.send(json.dumps(payload))
                
            except Exception as e:
                self.log(f"❌ Error notifying job completion: {str(e)}")
    
    def process_job(self, job: Dict) -> bool:
        """Process a single print job."""
        job_id = job.get('id', 'unknown')
        file_url = job.get('file_url', '')
        
        self.log(f"🔄 Processing job #{job_id}")
        
        # Check if printer is available
        printer_available, printer_name = self.is_printer_available()
        
        if not printer_available:
            error_msg = "No printer detected on this system"
            self.log(f"🖨️  {error_msg}")
            self.notify_job_complete(job_id, False, error_msg)
            return False
        
        # Download document
        document_data = self.download_document(file_url)
        if not document_data:
            error_msg = "Failed to download document"
            self.notify_job_complete(job_id, False, error_msg)
            return False
        
        # Print document
        print_success = self.print_document(document_data, printer_name, job)
        
        # Notify completion
        self.notify_job_complete(job_id, print_success, 
                               None if print_success else "Printing failed")
        
        return print_success
    
    def run(self):
        """Main loop to continuously monitor for print jobs via WebSocket."""
        self.log("🔄 Starting WebSocket connection")
        
        # Enable WebSocket debug logging if debug mode is enabled
        if self.debug:
            websocket.enableTrace(True)
        
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
        
        # Run WebSocket connection
        self.ws.run_forever()

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Vendor Print Client")
    parser.add_argument("--vendor-id", required=True, help="Vendor ID for identification")
    parser.add_argument("--url", default="ws://127.0.0.1:8000", help="Base WebSocket URL of the Django application")
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
    client = VendorPrintClient(
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