import cv2
import socket

class UdpVideoSender:
    def __init__(self, server_ip="127.0.0.1", server_port=5000):
        # Initialize object attributes
        self.server_ip = server_ip
        self.server_port = server_port
        
        # Setup standard UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Setup camera
        self.cap = cv2.VideoCapture(0)

    def start_sending(self):
        if not self.cap.isOpened():
            print("Error: Unable to open camera!")
            return

        print(f"Preparing to send video via UDP to {self.server_ip}:{self.server_port}...")
        print("Camera opened! Press 'q' in the video window to exit.")

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    break
                
                # Compress frame
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
                byte_data = encoded_frame.tobytes()
                
                # Send data packet
                self.sock.sendto(byte_data, (self.server_ip, self.server_port))
                print(f"Sent packet: {len(byte_data)} bytes        ", end='\r')
                
                cv2.imshow('HexaCall - UDP Sender', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                    
        except Exception as e:
            # Standard network error handling
            print(f"\nNetwork or execution error occurred: {e}")
            
        finally:
            # Ensure resources are cleaned up regardless of errors
            self.cleanup()

    def cleanup(self):
        self.cap.release()
        cv2.destroyAllWindows()
        self.sock.close()

# Initialize and run the object
if __name__ == "__main__":
    sender = UdpVideoSender()
    sender.start_sending()