import websocket
import json
import time
import sys
import os
import tempfile
import win32print
import win32api
import PyPDF2
from urllib.parse import urljoin

# Configuration
WEBSOCKET_URL = "ws://127.0.0.1:8000/ws/vendor/"  # Use 127.0.0.1 instead of localhost
VENDOR_ID = "1"  # Replace with the actual vendor ID

def print_pdf(pdf_path):
    """
    Print a PDF file to the default printer
    
    Args:
        pdf_path (str): Full path to the PDF file
    """
    try:
        # Check if file exists
        if not os.path.exists(pdf_path):
            print(f"Error: File not found at {pdf_path}")
            return False
            
        # Get the default printer
        printer_name = win32print.GetDefaultPrinter()
        if not printer_name:
            print("No default printer found!")
            return False
            
        print(f"Using printer: {printer_name}")
        
        # Create a temporary printer handle
        handle = win32print.OpenPrinter(printer_name)
        try:
            print(f"Printing file: {os.path.basename(pdf_path)}")
            # Use the default printing dialog and settings
            win32api.ShellExecute(
                0, 
                "printto", 
                pdf_path, 
                f'"{printer_name}"', 
                ".", 
                0
            )
            print("Print command sent successfully")
            return True
            
        finally:
            win32print.ClosePrinter(handle)
            
    except Exception as e:
        print(f"Error printing file: {e}")
        return False

def list_available_printers():
    """List all available printers on the system"""
    printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    print("Available printers:")
    for i, printer in enumerate(printers):
        print(f"  {i+1}. {printer[2]}")
    
    default = win32print.GetDefaultPrinter()
    print(f"\nDefault printer: {default}")
    return len(printers) > 0

def download_print_file(file_url, temp_dir, print_settings=None):
    """Download the print file from the server"""
    try:
        import requests
        response = requests.get(file_url)
        if response.status_code == 200:
            file_path = os.path.join(temp_dir, os.path.basename(file_url))
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            # Log print settings if available
            if print_settings:
                print(f"Print settings for {os.path.basename(file_url)}:")
                print(f"  Copies: {print_settings.get('copies', 'N/A')}")
                print(f"  Color: {print_settings.get('color', 'N/A')}")
                print(f"  Orientation: {print_settings.get('orientation', 'N/A')}")
                print(f"  Page Size: {print_settings.get('pageSize', 'N/A')}")
                print(f"  Page Range: {print_settings.get('pageRange', 'N/A')}")
                if print_settings.get('spiralBinding') == 'true':
                    print(f"  Spiral Binding: Yes")
                if print_settings.get('lamination') == 'true':
                    print(f"  Lamination: Yes")
            
            return file_path
        return None
    except Exception as e:
        print(f"Error downloading file: {e}")
        return None

def on_message(ws, message):
    print(f"Received: {message}")
    try:
        data = json.loads(message)
        message_type = data.get('type')
        
        if message_type == 'print_request':
            print("Print request detected!")
            file_url = data.get('file_url')
            print_settings = data.get('print_settings', {})
            if not file_url:
                print("No file URL provided in print request")
                return
                
            # Create temporary directory for downloaded files
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the file
                file_path = download_print_file(file_url, temp_dir, print_settings)
                if not file_path:
                    print("Failed to download print file")
                    return
                    
                # Print the file
                success = print_pdf(file_path)
                if success:
                    # Send success response back to server
                    response = {
                        "type": "print_status",
                        "status": "completed",
                        "request_id": data.get('request_id'),
                        "message": "Print job completed successfully"
                    }
                    ws.send(json.dumps(response))
                else:
                    # Send failure response
                    response = {
                        "type": "print_status",
                        "status": "failed",
                        "request_id": data.get('request_id'),
                        "message": "Failed to print file"
                    }
                    ws.send(json.dumps(response))
                    
        else:
            print(f"Message content: {data.get('message', 'No message content')}")
            
    except json.JSONDecodeError:
        print(f"Could not parse message as JSON: {message}")
    except Exception as e:
        print(f"Error processing message: {e}")

def on_error(ws, error):
    print(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"Connection closed with status {close_status_code}: {close_msg}")

def on_open(ws):
    print(f"Connected to WebSocket for Vendor {VENDOR_ID}")
    
    # Check for available printers
    if not list_available_printers():
        print("No printers detected! Halting...")
        ws.close()
        return

    def run(*args):
        while True:
            try:
                # Request print jobs
                message = {
                    "type": "request_print_jobs",
                    "vendor_id": VENDOR_ID
                }
                ws.send(json.dumps(message))
                print("Requested print jobs from server")
                time.sleep(5)  # Check every 5 seconds
            except Exception as e:
                print(f"Error in run loop: {e}")
                break

    import threading
    threading.Thread(target=run, daemon=True).start()

def connect_websocket():
    # Enable debug logging
    websocket.enableTrace(True)
    
    # Create WebSocket connection
    ws_url = f"{WEBSOCKET_URL}{VENDOR_ID}/"
    print(f"Connecting to: {ws_url}")
    
    ws = websocket.WebSocketApp(ws_url,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close,
                              on_open=on_open)
    
    return ws

if __name__ == "__main__":
    while True:
        try:
            ws = connect_websocket()
            ws.run_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            ws.close()
            sys.exit(0)
        except Exception as e:
            print(f"Connection lost: {e}")
            print("Reconnecting in 5 seconds...")
            time.sleep(5) 