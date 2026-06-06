import cv2
import socket

# 1. Network configuration (UDP Socket)
# 127.0.0.1 is the Localhost address (for local testing on your machine)
SERVER_IP = "127.0.0.1" 
SERVER_PORT = 5000      

# Initialize the network socket. SOCK_DGRAM specifies the UDP protocol.
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Preparing to send video via UDP to {SERVER_IP}:{SERVER_PORT}...")

# 2. Initialize Camera
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Unable to open camera!")
    exit()

print("Camera opened! Press 'q' in the video window to exit.")

while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    # Compress the frame to JPEG format with 80% quality (Phase 2 integration)
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
    result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
    
    # Convert the compressed frame into a byte string
    byte_data = encoded_frame.tobytes()
    
    # 3. TRANSMIT DATA OVER NETWORK
    # sendto() packages the byte_data and sends it directly to the target IP
    sock.sendto(byte_data, (SERVER_IP, SERVER_PORT))
    
    # Print status for monitoring
    print(f"Sent packet: {len(byte_data)} bytes        ", end='\r')
    
    cv2.imshow('HexaCall - UDP Sender', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Clean up resources
cap.release()
cv2.destroyAllWindows()
sock.close() # Close the network socket