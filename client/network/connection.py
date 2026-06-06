import socket

class NetworkConnection:
    """Class handling TCP and UDP socket connections."""
    
    def __init__(self):
        self.tcp_socket = None

    def connect_tcp(self, host: str, port: int) -> bool:
        """Establishes a basic TCP connection to the main server."""
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.settimeout(3.0)
            self.tcp_socket.connect((host, port))
            print(f"[*] Successfully connected to {host}:{port}")
            return True
        except Exception as e:
            print(f"[-] TCP Connection failed: {e}")
            return False

    def disconnect(self):
        """Closes the active network connection."""
        if self.tcp_socket:
            self.tcp_socket.close()
            print("[*] Disconnected from server.")
