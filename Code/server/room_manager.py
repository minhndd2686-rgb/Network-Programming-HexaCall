import logging
import threading
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

class RoomManager:
    def __init__(self, max_clients: int = 6):
        # clients: {client_id: {"conn": conn, "addr": addr, "room": room_id, "udp_addr": (ip, port)}}
        self.clients = {}
        # rooms: {room_id: [client_id1, client_id2, ...]}
        self.rooms = {}
        self.lock = threading.Lock()
        self.max_clients = max_clients

    def add_client(self, client_id, conn, addr):
        """add new client into list."""
        with self.lock:
            self.clients[client_id] = {
                "conn": conn,
                "addr": addr,
                "room": None,
                "udp_addr": None,
                "camera_on": True,      # Camera on by default
                "mic_muted": False      # Mic unmuted by default
            }
            logging.info("RoomManager: Added client %s", client_id)

    def is_client_in_room(self, client_id: int, room_id: int) -> bool:
        """Check if client is currently in the specified room."""
        with self.lock:
            return room_id in self.rooms and client_id in self.rooms[room_id]

    def get_client_room(self, client_id: int) -> int:
        """Get the room_id the client is currently in, or None."""
        with self.lock:
            if client_id in self.clients:
                return self.clients[client_id].get("room")
            return None

    def bind_udp_addr_if_allowed(self, client_id: int, room_id: int, udp_addr: tuple) -> bool:
        """
        Authorize and bind a UDP address.
        Returns True if authorized (packet should be routed), False otherwise.
        """
        with self.lock:
            if client_id not in self.clients:
                return False

            # Client must actually be in the claimed room
            actual_room = self.clients[client_id].get("room")
            if actual_room != room_id:
                return False

            # First UDP bind must come from the same IP used for TCP signaling.
            # This blocks first-packet hijack attempts from a different host.
            tcp_addr = self.clients[client_id].get("addr")
            if tcp_addr and udp_addr[0] != tcp_addr[0]:
                logging.warning(
                    "RoomManager: UDP IP mismatch for client %s (tcp=%s udp=%s)",
                    client_id,
                    tcp_addr,
                    udp_addr,
                )
                return False

            old_addr = self.clients[client_id].get("udp_addr")
            if old_addr is None:
                # First valid packet binds the UDP address after room and IP checks.
                self.clients[client_id]["udp_addr"] = udp_addr
                logging.info("RoomManager: UDP address for %s bound to %s", client_id, udp_addr)
                return True
            elif old_addr == udp_addr:
                # Address matches the binding
                return True
            else:
                # Packet from a different address claiming this client_id (possible spoofing)
                logging.warning("RoomManager: Spoof attempt? UDP address %s claiming client %s (bound to %s)", udp_addr, client_id, old_addr)
                return False

    def remove_client(self, client_id):
        """delete client clean rooms."""
        with self.lock:
            if client_id in self.clients:
                room_id = self.clients[client_id]["room"]
                if room_id:
                    self._leave_room_internal(client_id, room_id)
                del self.clients[client_id]
                logging.info("RoomManager: Removed client %s", client_id)

    def join_room(self, client_id, room_id):
        """Add the client to a specific room."""
        with self.lock:
            if client_id not in self.clients:
                return False

            if room_id not in self.rooms:
                self.rooms[room_id] = []

            if len(self.rooms[room_id]) >= self.max_clients:
                logging.info(f"Room {room_id} is full (max {self.max_clients}).")
                return False

            if client_id not in self.rooms[room_id]:
                self.rooms[room_id].append(client_id)
                self.clients[client_id]["room"] = room_id
                # Initialize camera/mic state
                self.clients[client_id]["camera_on"] = True
                self.clients[client_id]["mic_muted"] = False
                logging.info("RoomManager: Client %s joined room %s (camera_on=True, mic_muted=False)", client_id, room_id)
                return True
            return False

    def _leave_room_internal(self, client_id, room_id):
        """Internal function to remove a client from the room (without using a separate lock)"""
        if room_id in self.rooms and client_id in self.rooms[room_id]:
            self.rooms[room_id].remove(client_id)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    def leave_room(self, client_id, room_id):
        """Let the client leave the room."""
        with self.lock:
            self._leave_room_internal(client_id, room_id)
            if client_id in self.clients:
                self.clients[client_id]["room"] = None
                self.clients[client_id]["udp_addr"] = None
            logging.info("RoomManager: Client %s left room %s", client_id, room_id)
            return True

    def get_room_participants(self, room_id):
        """Get the list of client IDs in the room."""
        with self.lock:
            return list(self.rooms.get(room_id, []))

    def get_room_participants_with_state(self, room_id: int) -> list:
        """Return list of participant dicts with state for broadcast.

        Each entry: {client_id, camera_on, mic_muted}
        """
        with self.lock:
            participants = self.rooms.get(room_id, [])
            result = []
            for c_id in participants:
                if c_id in self.clients:
                    info = self.clients[c_id]
                    result.append({
                        "client_id": c_id,
                        "camera_on": info.get("camera_on", True),
                        "mic_muted": info.get("mic_muted", False)
                    })
            return result

    def get_room_connections(self, room_id):
        """Return copied TCP connections for room broadcasts."""
        with self.lock:
            participants = self.rooms.get(room_id, [])
            # Copy connection references while locked; caller sends outside lock.
            return [
                (c_id, self.clients[c_id]["conn"])
                for c_id in participants
                if c_id in self.clients
            ]

    def get_all_connections(self):
        """Return copied TCP connections for clean server shutdown."""
        with self.lock:
            return [
                (c_id, info["conn"])
                for c_id, info in self.clients.items()
            ]

    def get_client_count(self):
        """Return active TCP client count under lock."""
        with self.lock:
            return len(self.clients)

    def get_room_participants_udp(self, room_id, exclude_id=None):
        """Get the list of UDP addresses of all clients in the room, optionally excluding one."""
        udp_addrs = []
        with self.lock:
            participants = self.rooms.get(room_id, [])
            for c_id in participants:
                if c_id != exclude_id:
                    addr = self.clients[c_id].get("udp_addr")
                    if addr:
                        udp_addrs.append(addr)
        return udp_addrs

    def update_participant_state(self, client_id: int, camera_on: Optional[bool] = None, mic_muted: Optional[bool] = None) -> bool:
        """Update camera/mic state for a client, broadcast if changed.

        Returns True if state changed, False otherwise.
        """
        changed = False
        with self.lock:
            if client_id not in self.clients:
                return False
            if camera_on is not None and self.clients[client_id]["camera_on"] != camera_on:
                self.clients[client_id]["camera_on"] = camera_on
                changed = True
            if mic_muted is not None and self.clients[client_id]["mic_muted"] != mic_muted:
                self.clients[client_id]["mic_muted"] = mic_muted
                changed = True
        return changed
