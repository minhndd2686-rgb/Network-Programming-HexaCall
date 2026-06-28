import unittest
import socket
import threading
import time
import json
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.main_server import MasterServer
from Code.shared.protocol import pack_message, recv_message, PacketType

logging.getLogger().setLevel(logging.CRITICAL)

class TestRoomBroadcast(unittest.TestCase):
    def setUp(self):
        self.host = "127.0.0.1"
        self.tcp_port = 8012
        self.udp_port = 5012
        self.server = MasterServer(self.host, self.tcp_port, self.udp_port)
        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()
        time.sleep(0.5)

    def tearDown(self):
        self.server.stop()
        time.sleep(0.5)

    def connect_client(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((self.host, self.tcp_port))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.LOGIN)
        return s, payload["client_id"]

    def test_broadcast_on_join_leave(self):
        # Client A connects and joins
        sA, cidA = self.connect_client()
        sA.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 1}))
        mtype, pld = recv_message(sA)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertEqual(pld["participants"], [cidA])

        # Client B connects and joins
        sB, cidB = self.connect_client()
        sB.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 1}))

        # B should receive ROOM_STATE
        mtype, pld = recv_message(sB)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertCountEqual(pld["participants"], [cidA, cidB])

        # A should also receive ROOM_STATE
        mtype, pld = recv_message(sA)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertCountEqual(pld["participants"], [cidA, cidB])

        # Client B leaves room
        sB.sendall(pack_message(PacketType.LEAVE_ROOM, {"room_id": 1}))

        # B receives confirmation
        mtype, pld = recv_message(sB)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertEqual(pld["participants"], [])

        # A receives updated state
        mtype, pld = recv_message(sA)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertEqual(pld["participants"], [cidA])

        sA.close()
        sB.close()

    def test_broadcast_on_disconnect(self):
        sA, cidA = self.connect_client()
        sA.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 2}))
        recv_message(sA) # Ignore its own join

        sB, cidB = self.connect_client()
        sB.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 2}))
        recv_message(sB) # Ignore its own join

        mtype, pld = recv_message(sA) # A gets B's join
        self.assertCountEqual(pld["participants"], [cidA, cidB])

        # B disconnects abruptly without sending LEAVE_ROOM
        sB.close()

        # A should receive updated room state
        mtype, pld = recv_message(sA)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertEqual(pld["participants"], [cidA])

        sA.close()

if __name__ == "__main__":
    unittest.main()
