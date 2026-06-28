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

# Default server config
HOST = "0.0.0.0"
PORT = 8000
UDP_PORT = 5000
BACKLOG = 6
MAX_CLIENTS = 6  # Global concurrent client limit (Phase C)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class MasterServer:
    def __init__(self, host: str = HOST, tcp_port: int = PORT, udp_port: int = UDP_PORT):
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port

        # TCP listening socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.room_manager = RoomManager()

        # UDP video routing server
        self.udp_server = UdpVideoServer(
            host=self.host, port=self.udp_port, room_manager=self.room_manager
        )

        # Monotonic client ID counter (uint16 range for UDP header compatibility)
        self.client_counter = itertools.count(1)

        # Phase B: stop event lets _accept_loop exit cleanly without closing
        # the socket mid-accept (avoids WinError 10038 on Windows).
        self._stop_event = threading.Event()

        # Phase B: track handler threads so stop() can join them.
        # Protected by _threads_lock to allow concurrent append/remove.
        self._threads = []
        self._threads_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Bind, listen, and run accept loop. Blocks until stopped."""
        self.udp_server.start()

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
        """
        Signal the accept loop to exit, close all active client sockets,
        stop the UDP server, and close the listening socket.

        Idempotent: safe to call multiple times (e.g. from tearDown and
        from the start() finally block simultaneously during tests).
        """
        if self._stop_event.is_set():
            return
        self._stop_event.set()

        logging.info("MasterServer stopping...")

        # Close every active client TCP socket so handler threads unblock
        # from recv_message() and exit their loops cleanly.
        for cid, conn in self.room_manager.get_all_connections():
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass

        # Stop UDP routing thread
        self.udp_server.stop()

        # Close the listening socket (unblocks accept() if timeout hasn't fired)
        try:
            self.sock.close()
        except OSError:
            pass

        # Join handler threads with a short timeout each so we don't hang forever
        with self._threads_lock:
            threads_snapshot = list(self._threads)
        for th in threads_snapshot:
            th.join(timeout=1.0)

        logging.info("MasterServer stopped.")

    # ------------------------------------------------------------------
    # Accept loop
    # ------------------------------------------------------------------

    def _accept_loop(self):
        """
        Accept incoming TCP connections until _stop_event is set.

        Uses a 1 s socket timeout so the loop can check _stop_event
        periodically without blocking forever on Windows.
        """
        self.sock.settimeout(1.0)
        while not self._stop_event.is_set():
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                # Listening socket was closed by stop(); exit cleanly.
                break

            # Phase C: enforce global client limit before assigning id
            if self.room_manager.get_client_count() >= MAX_CLIENTS:
                logging.warning("Server full: rejecting connection from %s", addr)
                try:
                    send_message(conn, PacketType.ERROR, {"reason": "Server full"})
                except OSError:
                    pass
                conn.close()
                continue

            # client_id must fit in uint16 for UDP header (H field)
            client_id = next(self.client_counter)
            if client_id > 65535:
                logging.error("client_id overflow (> 65535); rejecting %s", addr)
                conn.close()
                continue

            logging.info("Client connected: %s (Assigned ID: %d)", addr, client_id)
            self.room_manager.add_client(client_id, conn, addr)

            th = threading.Thread(
                target=self.handle_client,
                args=(conn, addr, client_id),
                daemon=True,
                name=f"ClientHandler-{client_id}",
            )
            with self._threads_lock:
                self._threads.append(th)
            th.start()

    # ------------------------------------------------------------------
    # Broadcast helper
    # ------------------------------------------------------------------

    def _broadcast_room_state(self, room_id: int):
        """
        Broadcast updated ROOM_STATE to every current participant in room_id.

        Snapshot connections first (inside RoomManager.lock), then send
        outside the lock so a blocked socket send never deadlocks state
        operations. Per-client errors are caught and logged; one bad socket
        does not prevent delivery to other participants.
        """
        connections = self.room_manager.get_room_connections(room_id)
        participants = [cid for cid, _ in connections]
        for cid, c in connections:
            try:
                send_message(c, PacketType.ROOM_STATE, {
                    "room_id": room_id,
                    "participants": participants,
                })
            except (OSError, ConnectionError) as e:
                logging.warning(
                    "Broadcast ROOM_STATE to client %d failed (socket error): %s", cid, e
                )
            except Exception as e:
                logging.warning(
                    "Broadcast ROOM_STATE to client %d failed: %s", cid, e
                )

    # ------------------------------------------------------------------
    # Client handler
    # ------------------------------------------------------------------

    def handle_client(self, conn: socket.socket, addr, client_id: int):
        """
        Handle one TCP client in its own thread.

        Parses structured messages (JOIN_ROOM, LEAVE_ROOM) and responds
        with ROOM_STATE broadcasts or ERROR frames. Cleans up on exit and
        broadcasts the updated participant list to any remaining peers.
        """
        try:
            logging.info("Handler started for %s (id=%d)", addr, client_id)

            # Immediately confirm assignment so client knows its numeric id
            send_message(conn, PacketType.LOGIN, {"client_id": client_id})

            while not self._stop_event.is_set():
                msg_type, payload = recv_message(conn)
                if msg_type is None:
                    break  # client disconnected or malformed frame

                logging.info("MSG from id=%d type=%d payload=%s", client_id, msg_type, payload)

                if not isinstance(payload, dict):
                    send_message(conn, PacketType.ERROR, {"reason": "Invalid payload format"})
                    continue

                if msg_type == PacketType.JOIN_ROOM:
                    room_id_raw = payload.get("room_id")
                    if room_id_raw is None:
                        send_message(conn, PacketType.ERROR, {"reason": "Missing room_id"})
                        continue
                    if isinstance(room_id_raw, bool):
                        send_message(conn, PacketType.ERROR, {"reason": "Invalid room_id type"})
                        continue
                    try:
                        room_id = int(room_id_raw)
                        if not (0 <= room_id <= 65535):
                            raise ValueError()
                    except (ValueError, TypeError):
                        send_message(conn, PacketType.ERROR, {"reason": "Invalid room_id format"})
                        continue

                    success = self.room_manager.join_room(client_id, room_id)
                    if success:
                        # Broadcast to ALL participants (including requester)
                        self._broadcast_room_state(room_id)
                    else:
                        send_message(conn, PacketType.ERROR, {"reason": "Room full or already joined"})

                elif msg_type == PacketType.LEAVE_ROOM:
                    room_id_raw = payload.get("room_id")
                    if room_id_raw is None:
                        send_message(conn, PacketType.ERROR, {"reason": "Missing room_id"})
                        continue
                    if isinstance(room_id_raw, bool):
                        send_message(conn, PacketType.ERROR, {"reason": "Invalid room_id type"})
                        continue
                    try:
                        room_id = int(room_id_raw)
                        if not (0 <= room_id <= 65535):
                            raise ValueError()
                    except (ValueError, TypeError):
                        send_message(conn, PacketType.ERROR, {"reason": "Invalid room_id format"})
                        continue

                    self.room_manager.leave_room(client_id, room_id)
                    # Notify remaining room participants, then confirm to caller.
                    self._broadcast_room_state(room_id)
                    send_message(conn, PacketType.ROOM_STATE, {"room_id": room_id, "participants": []})

                else:
                    logging.warning("Unknown msg_type=%d from id=%d", msg_type, client_id)

        except Exception as e:
            logging.exception("Error in client handler %s: %s", addr, e)
        finally:
            # Read room before removing so we can broadcast to remaining peers
            old_room_id = self.room_manager.get_client_room(client_id)
            self.room_manager.remove_client(client_id)
            if old_room_id is not None:
                self._broadcast_room_state(old_room_id)

            # Explicit socket close; idempotent if stop() already closed it
            try:
                conn.close()
            except OSError:
                pass

            logging.info("Client disconnected %s (id=%d)", addr, client_id)

            # Remove this thread from tracking list
            current = threading.current_thread()
            with self._threads_lock:
                try:
                    self._threads.remove(current)
                except ValueError:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Master TCP Server")
    parser.add_argument("--host", default=HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT, help="UDP bind port")
    args = parser.parse_args()

    server = MasterServer(args.host, args.port, args.udp_port)
    server.start()
