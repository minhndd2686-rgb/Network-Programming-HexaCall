import socket
import threading
import logging
import sys
import os

# Add path to import shared module if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from Code.shared.protocol import unpack_udp_chunk
except ImportError:
    # Fallback if running directly from the server folder
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from Code.shared.protocol import unpack_udp_chunk

class UdpVideoServer:
    """
    UDP Video Server handling video streaming.
    """
    def __init__(self, host='0.0.0.0', port=5000, room_manager=None):
        self.host = host
        self.port = port
        self.room_manager = room_manager
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allows quick rebinding on Windows/Linux
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self._stop_event = threading.Event()
        self._thread = None
        self.logger = logging.getLogger("UdpVideoServer")

    def start(self):
        """Khởi chạy UDP server trong thread riêng."""
        try:
            self.sock.bind((self.host, self.port))
            self.logger.info(f"UDP Video Server started on {self.host}:{self.port}")

            self._thread = threading.Thread(target=self._receive_loop, name="UdpServerThread", daemon=True)
            self._thread.start()
        except Exception as e:
            self.logger.error(f"Failed to start UDP Server: {e}")

    def stop(self):
        """Dừng server và đóng socket."""
        self.logger.info("Stopping UDP Video Server...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.sock.close()
        self.logger.info("UDP Video Server stopped.")

    def _receive_loop(self):
        """Vòng lặp nhận dữ liệu, không block vĩnh viễn nhờ timeout."""
        self.sock.settimeout(1.0) # 1 second timeout to check stop_event
        while not self._stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(65535) # Max UDP size
                if not data:
                    continue

                # 1. Validate packet header
                unpacked = unpack_udp_chunk(data)
                if not unpacked:
                    # Packet not in HexaCall format, skipping
                    continue

                client_id, room_id, frame_id, chunk_idx, total_chunks, payload = unpacked

                # 2. Handling routing
                # Phase 2: Echo back (Single-client streaming test)
                self._echo_packet(data, addr)

                # Phase 3 (Next): Routing qua RoomManager
                # self._route_packet(data, room_id, client_id)

            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    self.logger.error(f"UDP receive error: {e}")

    def _echo_packet(self, data, addr):
        """Echo the data back to the client itself."""
        try:
            self.sock.sendto(data, addr)
        except Exception as e:
            self.logger.error(f"Failed to echo packet to {addr}: {e}")

    def _route_packet(self, data, room_id, sender_id):
        """Forward data to other members in the room."""
        if not self.room_manager:
            return

        participants = self.room_manager.get_room_participants(room_id)
        for p_id in participants:
            if p_id != sender_id:
                # Need to map client_id (TCP) to UDP address (IP, Port)
                # or the client has to send the UDP port registration first.
                pass
