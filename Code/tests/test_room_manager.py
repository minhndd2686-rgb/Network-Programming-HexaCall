import unittest
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.room_manager import RoomManager

logging.getLogger().setLevel(logging.CRITICAL)


class DummyConn:
    pass


class TestRoomManager(unittest.TestCase):
    def test_connection_snapshots_and_count(self):
        rm = RoomManager(max_clients=6)
        c1 = DummyConn()
        c2 = DummyConn()

        rm.add_client(1, c1, ("127.0.0.1", 10001))
        rm.add_client(2, c2, ("127.0.0.1", 10002))
        self.assertEqual(rm.get_client_count(), 2)

        self.assertTrue(rm.join_room(1, 10))
        self.assertTrue(rm.join_room(2, 10))

        room_connections = rm.get_room_connections(10)
        self.assertEqual(room_connections, [(1, c1), (2, c2)])

        all_connections = rm.get_all_connections()
        self.assertEqual(all_connections, [(1, c1), (2, c2)])

        # Returned lists are snapshots; mutating them must not affect manager state.
        room_connections.clear()
        self.assertEqual(rm.get_room_participants(10), [1, 2])

    def test_udp_bind_rejects_source_ip_mismatch(self):
        rm = RoomManager(max_clients=6)
        rm.add_client(1, DummyConn(), ("127.0.0.1", 10001))
        self.assertTrue(rm.join_room(1, 10))

        allowed = rm.bind_udp_addr_if_allowed(1, 10, ("127.0.0.2", 50000))
        self.assertFalse(allowed)

        # Legitimate same-IP bind still succeeds after mismatch is rejected.
        allowed = rm.bind_udp_addr_if_allowed(1, 10, ("127.0.0.1", 50001))
        self.assertTrue(allowed)

    def test_udp_bind_rejects_wrong_room_and_second_address(self):
        rm = RoomManager(max_clients=6)
        rm.add_client(1, DummyConn(), ("127.0.0.1", 10001))
        self.assertTrue(rm.join_room(1, 10))

        self.assertFalse(rm.bind_udp_addr_if_allowed(1, 11, ("127.0.0.1", 50000)))
        self.assertTrue(rm.bind_udp_addr_if_allowed(1, 10, ("127.0.0.1", 50000)))
        self.assertFalse(rm.bind_udp_addr_if_allowed(1, 10, ("127.0.0.1", 50001)))


if __name__ == "__main__":
    unittest.main()
