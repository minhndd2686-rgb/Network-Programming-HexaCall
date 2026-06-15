import socket
import threading
import logging
import argparse

from room_manager import RoomManager
from udp_video_server import UdpVideoServer

#default config
HOST = "0.0.0.0"
PORT = 8000
UDP_PORT = 5000
BACKLOG = 6
RECV_BUF = 4096

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

class MasterServer:
    def __init__(self, host: str = HOST, tcp_port: int = PORT, udp_port: int = UDP_PORT):
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port

        # TCP Setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.room_manager = RoomManager()

        # UDP Setup
        self.udp_server = UdpVideoServer(host=self.host, port=self.udp_port, room_manager=self.room_manager)

    def start(self):
        # Start UDP Server
        self.udp_server.start()

        # Start TCP Server
        self.sock.bind((self.host, self.tcp_port))
        self.sock.listen(BACKLOG)
        logging.info("MasterServer (TCP) listening on %s:%d", self.host, self.tcp_port)
        try:
            self._accept_loop()
        except KeyboardInterrupt:
            logging.info("Shutting down server (KeyboardInterrupt)")
        finally:
            self.stop()

    def stop(self):
        """Cleanup all server resources."""
        logging.info("MasterServer stopping...")
        self.udp_server.stop()
        self.sock.close()
        logging.info("MasterServer stopped.")

    def _accept_loop(self):
        self.sock.settimeout(1.0)  # add timeout to catch keyboardInterupt
        while True:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue

            client_id = f"{addr[0]}:{addr[1]}"
            logging.info(f"Client connected: {client_id}")

            self.room_manager.add_client(client_id, conn,addr)

            th = threading.Thread(
                target = self.handle_client,
                args = (conn,addr,client_id),
                daemon= True
            )
            th.start()

            # logging.info("Client connected from %s", addr)
            # th = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            # th.start()

    def handle_client(self, conn: socket.socket, addr, client_id):
        try:
            with conn:
                logging.info("Handler started for %s", addr)
                while True:
                    data = conn.recv(RECV_BUF)
                    if not data:
                        break

                    msg = data.decode('utf-8', errors='ignore').strip()
                    conn.sendall(msg.encode())
                    logging.info(f"MSG from {client_id}: {msg}")
                    logging.debug("Received %d bytes from %s", len(data), addr)
        except Exception as e:
            logging.exception("Error in client handler %s: %s", addr, e)
        finally:
            self.room_manager.remove_client(client_id)
            logging.info("Client disconnected %s", addr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Master TCP Server")
    parser.add_argument("--host", default=HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port")
    args = parser.parse_args()

    server = MasterServer(args.host, args.port)
    server.start()