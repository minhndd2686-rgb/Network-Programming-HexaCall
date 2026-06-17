import socket

def run_multiclient_server(host='0.0.0.0', port=5000):
    # Initialize UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((host, port))
    
    # Store unique addresses of clients (Maximum 6)
    active_clients = set()
    
    print(f"Phase 3: Routing Server is running on port {port}. Waiting for clients...")

    while True:
        try:
            # 1. Receive incoming frame bytes
            data, client_addr = server_socket.recvfrom(65535)
            
            # 2. Register new client if room is not full (Max 6)
            if client_addr not in active_clients:
                if len(active_clients) < 6:
                    active_clients.add(client_addr)
                    print(f"[JOIN] Client {client_addr} joined. Room size: {len(active_clients)}/6")
                else:
                    # Room is full, ignore new connections
                    continue 

            # 3. Routing Logic: Forward the frame to ALL OTHER active clients in the room
            for other_client in list(active_clients):
                if other_client != client_addr:
                    server_socket.sendto(data, other_client)
                    
        except Exception as e:
            print(f"Server error: {e}")

if __name__ == "__main__":
    run_multiclient_server()