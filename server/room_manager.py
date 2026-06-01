import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

class RoomManager:
    def __init__(self):
        # Lưu trữ client: {client_id: {"conn": conn, "addr": addr, "room": room_id}}
        self.clients = {}
        # Lưu trữ phòng: {room_id: [client_id1, client_id2, ...]}
        self.rooms = {}
        self.lock = threading.Lock()

    def add_client(self, client_id, conn, addr):
        """Thêm client mới vào danh sách quản lý chung."""
        with self.lock:
            self.clients[client_id] = {
                "conn": conn,
                "addr": addr,
                "room": None
            }
            logging.info("RoomManager: Added client %s", client_id)

    def remove_client(self, client_id):
        """Xóa client và dọn dẹp khỏi các phòng."""
        with self.lock:
            if client_id in self.clients:
                room_id = self.clients[client_id]["room"]
                if room_id:
                    self._leave_room_internal(client_id, room_id)
                del self.clients[client_id]
                logging.info("RoomManager: Removed client %s", client_id)

    def join_room(self, client_id, room_id):
        """Cho client tham gia vào một phòng cụ thể."""
        with self.lock:
            if client_id not in self.clients:
                return False

            if room_id not in self.rooms:
                self.rooms[room_id] = []

            if client_id not in self.rooms[room_id]:
                self.rooms[room_id].append(client_id)
                self.clients[client_id]["room"] = room_id
                logging.info("RoomManager: Client %s joined room %s", client_id, room_id)
                return True
            return False

    def _leave_room_internal(self, client_id, room_id):
        """Hàm nội bộ để xóa client khỏi phòng (không dùng lock riêng)"""
        if room_id in self.rooms and client_id in self.rooms[room_id]:
            self.rooms[room_id].remove(client_id)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    def leave_room(self, client_id, room_id):
        """Cho client rời khỏi phòng."""
        with self.lock:
            self._leave_room_internal(client_id, room_id)
            if client_id in self.clients:
                self.clients[client_id]["room"] = None
            logging.info("RoomManager: Client %s left room %s", client_id, room_id)
            return True

    def get_room_participants(self, room_id):
        """Lấy danh sách ID các client trong phòng."""
        with self.lock:
            return list(self.rooms.get(room_id, []))
