import cv2
import socket
import numpy as np

# 1. Network configuration (Listen on port 5000)
LISTEN_IP = "127.0.0.1"
LISTEN_PORT = 5000

# Initialize socket and BIND it to the port to start listening
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening for UDP video packets on {LISTEN_IP}:{LISTEN_PORT}...")

while True:
    # 2. Receive data packet (buffer size 65536 is standard for UDP maximum)
    data, addr = sock.recvfrom(65536)
    
    # 3. Decode byte data back into an image frame
    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 4. Display the received video
    if frame is not None:
        cv2.imshow('HexaCall - UDP Receiver', frame)
        
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Clean up resources
cv2.destroyAllWindows()
sock.close()