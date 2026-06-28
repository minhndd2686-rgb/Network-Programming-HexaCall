import unittest
import socket
import threading
import time
import json
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.room_manager import RoomManager
from Code.server.udp_video_server import UdpVideoServer
from Code.server.main_server import MasterServer
from Code.shared.protocol import pack_message, recv_message, PacketType, pack_udp_chunk

# Suppress logs during test
logging.getLogger("UdpVideoServer").setLevel(logging.CRITICAL)
logging.getLogger("RoomManager").setLevel(logging.CRITICAL)

class TestHexaCallFixes(unittest.TestCase):
    def setUp(self):
        self.host = "127.0.0.1"
        self.tcp_port = 8011
        self.udp_port = 5011
        self.server = MasterServer(self.host, self.tcp_port, self.udp_port)
        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()
        time.sleep(0.5)

    def tearDown(self):
        self.server.stop()
        time.sleep(0.5)

    def connect_client(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((self.host, self.tcp_port))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.LOGIN)
        client_id = payload["client_id"]
        return s, client_id

    def test_tcp_room_validation(self):
        s, cid = self.connect_client()

        # 1. Missing room_id
        s.sendall(pack_message(PacketType.JOIN_ROOM, {}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("Missing room_id", payload.get("reason", ""))

        # 2. String invalid room_id
        s.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": "room1"}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("Invalid room_id format", payload.get("reason", ""))

        # 3. Boolean room_id
        s.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": True}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("Invalid room_id type", payload.get("reason", ""))

        # 4. Out of range room_id
        s.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 70000}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("Invalid room_id format", payload.get("reason", ""))

        # 5. Out of range room_id (negative)
        s.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": -5}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("Invalid room_id format", payload.get("reason", ""))

        # 6. Valid room_id (int)
        s.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 1}))
        mtype, payload = recv_message(s)
        self.assertEqual(mtype, PacketType.ROOM_STATE)
        self.assertEqual(payload.get("room_id"), 1)
        self.assertIn(cid, payload.get("participants", []))

        s.close()

    def test_udp_hijacking_and_auth(self):
        # Setup Client A
        sA, cidA = self.connect_client()
        sA.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 1}))
        recv_message(sA) # consumes room state

        # Setup Client B (receives A's stream)
        sB, cidB = self.connect_client()
        sB.sendall(pack_message(PacketType.JOIN_ROOM, {"room_id": 1}))
        recv_message(sB) # consumes room state

        # Create sockets for UDP
        udpA = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udpA.bind((self.host, 0))

        udpB = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udpB.bind((self.host, 0))
        udpB.settimeout(0.5)

        # Create attacker UDP socket
        udp_attacker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_attacker.bind((self.host, 0))

        # First packet from client A should bind client A's address
        pkt = pack_udp_chunk(cidA, 1, 100, 0, 1, b"FRAME_DATA_A")
        udpA.sendto(pkt, (self.host, self.udp_port))

        # Attacker tries to hijack by claiming client_id=cidA and sending from attacker's port
        pkt_attacker = pack_udp_chunk(cidA, 1, 101, 0, 1, b"SPOOFED_DATA")
        udp_attacker.sendto(pkt_attacker, (self.host, self.udp_port))

        # Client A sends subsequent valid packet from the bound port
        pkt2 = pack_udp_chunk(cidA, 1, 102, 0, 1, b"FRAME_DATA_A_2")
        udpA.sendto(pkt2, (self.host, self.udp_port))

        # Client B must only receive from client A's actual UDP port.
        # But wait: when routing, server forwards the EXACT packet (which has cidA header).
        # We need to see if client B gets spoofed packet or valid packets.
        # Let's bind udpB address first so B gets routed traffic.
        pktB = pack_udp_chunk(cidB, 1, 200, 0, 1, b"FRAME_DATA_B")
        udpB.sendto(pktB, (self.host, self.udp_port))

        # Clear any buffered packets on B
        while True:
            try:
                udpB.recvfrom(65535)
            except socket.timeout:
                break

        # A sends valid packet
        udpA.sendto(pkt2, (self.host, self.udp_port))

        try:
            data, _ = udpB.recvfrom(65535)
            # Expecting to receive data from frame 102
            self.assertIn(b"FRAME_DATA_A_2", data)
        except socket.timeout:
            self.fail("Client B did not receive Client A's valid packet")

        # Now attacker sends spoofed data claiming to be cidA
        udp_attacker.sendto(pkt_attacker, (self.host, self.udp_port))

        try:
            data, _ = udpB.recvfrom(65535)
            # If received, fail (hijack succeeded). We expect timeout since server drops it.
            if b"SPOOFED_DATA" in data:
                self.fail("Security bypass: Spoofed packet was routed to client B")
        except socket.timeout:
            # Expected! The spoofed packet was dropped and not routed
            pass

        # Cleanup
        sA.close()
        sB.close()
        udpA.close()
        udpB.close()
        udp_attacker.close()

if __name__ == "__main__":
    unittest.main()
