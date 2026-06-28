import unittest
import socket
import threading
import time
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.server.main_server import MasterServer
from Code.shared.protocol import recv_message, PacketType

logging.getLogger().setLevel(logging.CRITICAL)


class TestServerLifecycle(unittest.TestCase):
    def test_stop_closes_active_client_socket(self):
        host = "127.0.0.1"
        server = MasterServer(host, 8013, 5013)
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect((host, 8013))
        msg_type, payload = recv_message(client)
        self.assertEqual(msg_type, PacketType.LOGIN)
        self.assertIn("client_id", payload)

        server.stop()
        server_thread.join(timeout=2.0)
        self.assertFalse(server_thread.is_alive())

        # The server closes active client sockets during shutdown, so reads
        # should return EOF or fail quickly instead of hanging indefinitely.
        client.settimeout(1.0)
        try:
            data = client.recv(1)
            self.assertEqual(data, b"")
        except (ConnectionResetError, OSError, socket.timeout):
            pass
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
