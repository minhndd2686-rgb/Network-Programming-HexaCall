import cv2
import socket
import numpy as np

class UdpVideoReceiver:
    def __init__(self, listen_ip="127.0.0.1", listen_port=5000):
        # Initialize receiver information
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        
        # Setup socket and bind
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.listen_ip, self.listen_port))

    def start_listening(self):
        print(f"Listening for UDP video packets on {self.listen_ip}:{self.listen_port}...")

        try:
            while True:
                # Receive data
                data, addr = self.sock.recvfrom(65536)
                
                # Decompress frame
                nparr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    cv2.imshow('HexaCall - UDP Receiver', frame)
                    
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                    
        except Exception as e:
            print(f"\nNetwork or execution error occurred: {e}")
            
        finally:
            self.cleanup()

    def cleanup(self):
        cv2.destroyAllWindows()
        self.sock.close()

# Initialize and run the object
if __name__ == "__main__":
    receiver = UdpVideoReceiver()
    receiver.start_listening()