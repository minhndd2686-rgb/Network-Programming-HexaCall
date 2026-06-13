import socket

def run_server(host='0.0.0.0', port=5000):
    # Initialize UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((host, port))
    
    print(f"Echo Server is listening on port {port}...")

    while True:
        # 1. Receive byte stream from client (max 65535 bytes for UDP)
        data, client_address = server_socket.recvfrom(65535)
        
        # 2. Echo the exact same byte stream back to the client
        server_socket.sendto(data, client_address)

if __name__ == "__main__":
    run_server()