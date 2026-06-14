import socket
import threading
import cv2
import numpy as np

# Import the FrameProcessor class from the media module
from media.frame_processor import FrameProcessor

def send_video_stream(sock, server_addr, processor, stop_event):
    """Background thread: Continuously capture, compress, and send frames"""
    # Check if the main thread has signaled to stop
    while not stop_event.is_set():
        compressed_bytes = processor.capture_and_compress()
        if compressed_bytes:
            try:
                sock.sendto(compressed_bytes, server_addr)
            except ConnectionResetError:
                # Server is down, ICMP Port Unreachable received
                print("[Sender Thread] Server forcibly closed the connection.")
                break
            except Exception as e:
                print(f"[Sender Thread] Unexpected error: {e}")
                break

def run_client():
    # Use localhost for testing the echo pipeline
    server_address = ('127.0.0.1', 5000) 
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.bind(('0.0.0.0', 0))
    
    # Initialize the G3 media processor
    processor = FrameProcessor()

    # Create an event flag to synchronize threads
    stop_event = threading.Event()

    # Create a daemon thread dedicated to sending frames
    sender_thread = threading.Thread(
        target=send_video_stream, 
        args=(client_socket, server_address, processor, stop_event), 
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
                stop_event.set() # Signal sender thread to stop
                break

        except ConnectionResetError:
            print("[Main Thread] Connection Lost! Server is down.")
            # Signal sender thread to stop capturing and sending
            stop_event.set() 
            
            # Render a fallback UI indicating connection loss
            error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(error_frame, "CONNECTION LOST!", (120, 240), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
            cv2.putText(error_frame, "Server is down. Closing in 3s...", (150, 300), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            cv2.imshow("Phase 2: Echo Test GUI", error_frame)
            cv2.waitKey(3000) # Wait for 3 seconds so the user can read the message
            break
            
        except Exception as e:
            print(f"Connection error: {e}")
            stop_event.set()
            break
            
    # Cleanup resources safely
    processor.cleanup()
    client_socket.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_client()