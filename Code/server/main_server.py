import socket
import threading
import logging
import argparse
import sys
import os

sys.path.append(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)
from server.room_manager import RoomManager    
from shared.protocol import (
    send_message,
    recv_message,
    PacketType
)

#default config
HOST = "0.0.0.0"
PORT = 8000
BACKLOG = 6
RECV_BUF = 4096

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

class MasterServer:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Giúp restart nhanh khi dev
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.room_manager = RoomManager()

    def start(self):
        self.sock.bind((self.host, self.port))
        self.sock.listen(BACKLOG)
        logging.info("MasterServer listening on %s:%d", self.host, self.port)
        try:
            self._accept_loop()
        except KeyboardInterrupt:
            logging.info("Shutting down server (KeyboardInterrupt)")
        finally:
            self.sock.close()

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
                
                # === STEP 1: LOGIN HANDSHAKE ===
                logging.info("Sending LOGIN packet to %s", client_id)
                send_message(conn, PacketType.LOGIN, {"client_id": client_id})
                
                # === STEP 2: WAIT FOR JOIN_ROOM ===
                msg_type, payload = recv_message(conn)
                if msg_type != PacketType.JOIN_ROOM:
                    logging.error(
                        "Expected JOIN_ROOM from %s, got %s",
                        client_id, msg_type
                    )
                    return
                
                room_id = payload.get("room_id")
                if not room_id:
                    logging.error("JOIN_ROOM missing room_id from %s", client_id)
                    send_message(
                        conn,
                        PacketType.ERROR,
                        {"reason": "Missing room_id"}
                    )
                    return
                
                # === STEP 3: JOIN ROOM ===
                if not self.room_manager.join_room(client_id, room_id):
                    logging.error("Failed to join room %s: %s", room_id, client_id)
                    send_message(
                        conn,
                        PacketType.ERROR,
                        {"reason": f"Failed to join room {room_id}"}
                    )
                    return
                
                # === STEP 4: SEND ROOM_STATE ===
                participants = self.room_manager.get_room_participants(room_id)
                logging.info(
                    "Sending ROOM_STATE to %s (room=%s, participants=%s)",
                    client_id, room_id, participants
                )
                send_message(
                    conn,
                    PacketType.ROOM_STATE,
                    {"room_id": room_id, "participants": participants}
                )
                
                # === STEP 5: KEEP ALIVE ===
                # Connection remains open for future messages (CHAT, VIDEO_DATA, LEAVE_ROOM)
                while True:
                    msg_type, payload = recv_message(conn)
                    if msg_type is None:
                        # Client disconnected
                        break
                    logging.debug("Received message type %s from %s", msg_type, client_id)
                    # TODO: Handle other message types (CHAT, LEAVE_ROOM, etc.)
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