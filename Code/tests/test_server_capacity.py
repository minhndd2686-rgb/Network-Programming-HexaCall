import unittest
import socket
import threading
import time
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.main_server import MasterServer, MAX_CLIENTS
from Code.shared.protocol import recv_message, PacketType

logging.getLogger().setLevel(logging.CRITICAL)


class TestServerCapacity(unittest.TestCase):
    def test_max_clients_rejection(self):
        host = "127.0.0.1"
        tcp_port = 8014
        server = MasterServer(host, tcp_port, 5014)

        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        clients = []
        # Connect MAX_CLIENTS successfully
        for _ in range(MAX_CLIENTS):
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect((host, tcp_port))
            mtype, pld = recv_message(client)
            self.assertEqual(mtype, PacketType.LOGIN)
            clients.append(client)

        # 7th client connects, should be rejected immediately
        extra_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        extra_client.settimeout(2.0)
        extra_client.connect((host, tcp_port))

        mtype, pld = recv_message(extra_client)
        self.assertEqual(mtype, PacketType.ERROR)
        self.assertIn("reason", pld)
        self.assertEqual(pld["reason"], "Server full")

        # Socket should be closed by server, further reads return None or EOF
        try:
            extra_client.settimeout(0.5)
            data = extra_client.recv(1)
            self.assertEqual(data, b"")
        except (ConnectionResetError, OSError):
            pass

        extra_client.close()

        # Clean up valid clients
        for c in clients:
            c.close()

        server.stop()
        server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
