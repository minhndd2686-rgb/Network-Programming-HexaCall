import socket
import threading
import cv2

# Import the core media processor
from media.frame_processor import FrameProcessor

def send_video_stream(sock, server_addr, processor):
    """Background thread: Capture, compress, and send frames to server"""
    while True:
        compressed_bytes = processor.capture_and_compress()
        if compressed_bytes:
            sock.sendto(compressed_bytes, server_addr)

def receive_video_stream(sock, processor, frames_dict):
    """Background thread: Receive multiple streams and bind to sender IDs"""
    while True:
        try:
            data, sender_addr = sock.recvfrom(65535)
            # Decompress bytes back into an OpenCV frame
            frame = processor.decompress_to_frame(data)
            
            if frame is not None:
                # Update the specific UI slot dictionary based on sender's address
                # sender_addr acts as the temporary ID (IP, Port)
                frames_dict[sender_addr] = frame
        except Exception as e:
            break

def run_client():
    server_address = ('127.0.0.1', 5000)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Fix WinError 10022 by binding to a random available port
    client_socket.bind(('0.0.0.0', 0)) 
    
    processor = FrameProcessor()
    
    # Dictionary to store frames from different clients (Simulating UI Grid slots)
    peer_frames = {}

    # Thread 1: Sending your own camera feed
    threading.Thread(
        target=send_video_stream, 
        args=(client_socket, server_address, processor), 
        daemon=True
    ).start()

    # Thread 2: Receiving feeds from up to 5 other clients
    threading.Thread(
        target=receive_video_stream, 
        args=(client_socket, processor, peer_frames), 
        daemon=True
    ).start()

    # Send a tiny dummy packet to register this client with the server
    client_socket.sendto(b'JOIN', server_address)
    print("Connected to Phase 3 Server. Waiting for other clients...")

    # Main Thread: Render the frames (UI Logic)
    while True:
        # Loop through all received frames and display them in separate windows
        # The UI team will later combine these into a single 6-slot grid
        for client_id, frame in list(peer_frames.items()):
            window_name = f"Grid Slot: {client_id[1]}" # Using port as dummy ID
            cv2.imshow(window_name, frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    processor.cleanup()
    client_socket.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_client()