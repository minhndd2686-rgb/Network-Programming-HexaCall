import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

class RoomManager:
    def __init__(self, max_clients: int = 6):
        # clients: {client_id: {"conn": conn, "addr": addr, "room": room_id}}
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
                "room": None
            }
            logging.info("RoomManager: Added client %s", client_id)

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
                logging.info("RoomManager: Client %s joined room %s", client_id, room_id)
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
            logging.info("RoomManager: Client %s left room %s", client_id, room_id)
            return True

    def get_room_participants(self, room_id):
        """Get the list of client IDs in the room."""
        with self.lock:
            return list(self.rooms.get(room_id, []))
