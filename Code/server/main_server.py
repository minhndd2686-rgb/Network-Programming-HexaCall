import socket
import threading
import logging
import argparse
import sys
import os
import itertools

# Add project root to sys.path to import shared modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.room_manager import RoomManager
from Code.server.udp_video_server import UdpVideoServer
from Code.shared.protocol import recv_message, send_message, PacketType

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

        # Client ID counter (use itertools.count to ensure monotonically increasing ints)
        self.client_counter = itertools.count(1)

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

            # client_id is int for protocol compatibility (monotonic counter)
            client_id = next(self.client_counter)
            logging.info(f"Client connected: {addr} (Assigned ID: {client_id})")

            # Store client using numeric ID (do NOT use addr/IP:port as identifier)
            self.room_manager.add_client(client_id, conn, addr)

            th = threading.Thread(
                target = self.handle_client,
                args = (conn, addr, client_id),
                daemon = True
            )
            th.start()

            # logging.info("Client connected from %s", addr)
            # th = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            # th.start()

    def handle_client(self, conn: socket.socket, addr, client_id: int):
        """
        Handle one TCP client in its own thread.
        Parses structured messages (LOGIN, JOIN_ROOM, LEAVE_ROOM)
        and replies with ROOM_STATE or ERROR.
        """
        try:
            logging.info("Handler started for %s (id=%d)", addr, client_id)

            # Immediately confirm assignment so client knows its numeric id
            send_message(conn, PacketType.LOGIN, {"client_id": client_id})

            while True:
                msg_type, payload = recv_message(conn)
                if msg_type is None:
                    break  # Client disconnected or malformed frame

                logging.info("MSG from id=%d type=%d payload=%s", client_id, msg_type, payload)

                if msg_type == PacketType.JOIN_ROOM:
                    room_id = payload.get("room_id")
                    if room_id is None:
                        send_message(conn, PacketType.ERROR, {"reason": "Missing room_id"})
                        continue

                    success = self.room_manager.join_room(client_id, room_id)
                    if success:
                        participants = self.room_manager.get_room_participants(room_id)
                        send_message(conn, PacketType.ROOM_STATE, {
                            "room_id": room_id,
                            "participants": participants,
                        })
                    else:
                        send_message(conn, PacketType.ERROR, {"reason": "Room full or already joined"})

                elif msg_type == PacketType.LEAVE_ROOM:
                    room_id = payload.get("room_id")
                    if room_id is None:
                        send_message(conn, PacketType.ERROR, {"reason": "Missing room_id"})
                        continue
                    self.room_manager.leave_room(client_id, room_id)
                    send_message(conn, PacketType.ROOM_STATE, {"room_id": room_id, "participants": []})

                else:
                    logging.warning("Unknown msg_type=%d from id=%d", msg_type, client_id)

        except Exception as e:
            logging.exception("Error in client handler %s: %s", addr, e)
        finally:
            self.room_manager.remove_client(client_id)
            logging.info("Client disconnected %s (id=%d)", addr, client_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Master TCP Server")
    parser.add_argument("--host", default=HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port")
    args = parser.parse_args()

    server = MasterServer(args.host, args.port)
    server.start()
