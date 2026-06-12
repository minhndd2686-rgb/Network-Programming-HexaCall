import socket
import threading
import cv2

# Import the FrameProcessor class from the media module
from media.frame_processor import FrameProcessor

def send_video_stream(sock, server_addr, processor):
    """Background thread: Continuously capture, compress, and send frames"""
    while True:
        compressed_bytes = processor.capture_and_compress()
        if compressed_bytes:
            sock.sendto(compressed_bytes, server_addr)

def run_client():
    # Use localhost for testing the echo pipeline
    server_address = ('127.0.0.1', 5000) 
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.bind(('0.0.0.0', 0))
    # Initialize the G3 media processor
    processor = FrameProcessor()

    # Create a daemon thread dedicated to sending frames
    # This prevents the capturing process from blocking the receiving/rendering process
    sender_thread = threading.Thread(
        target=send_video_stream, 
        args=(client_socket, server_address, processor), 
        daemon=True
    )
    sender_thread.start()

    print("Waiting for server response... Press 'q' on the camera window to exit.")
    
    # Main thread: Receive echoed frames and render UI
    while True:
        try:
            # 1. Receive echoed byte stream from Server
            data, _ = client_socket.recvfrom(65535)
            
            # 2. Decompress bytes back into an OpenCV frame
            frame = processor.decompress_to_frame(data)
            
            # 3. Render on UI
            if frame is not None:
                cv2.imshow("Phase 2: Echo Test GUI", frame)

            # Exit condition
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        except Exception as e:
            print(f"Connection error: {e}")
            break
            
    # Cleanup resources
    processor.cleanup()
    client_socket.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_client()