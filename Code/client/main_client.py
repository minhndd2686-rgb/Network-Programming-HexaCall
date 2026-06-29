import socket
import threading
import logging
import sys
import os
import argparse

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.client.media.frame_processor import FrameProcessor
from Code.shared.protocol import (
    recv_message, send_message, PacketType,
    chunk_frame, unpack_udp_chunk, FrameReassembler
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Timeout (seconds) for initial TCP connect + LOGIN handshake.
# If the server is unreachable or silent, fail fast within this window.
TCP_CONNECT_TIMEOUT = 5.0

class HexaClient:
    def __init__(self, host='127.0.0.1', tcp_port=8000, udp_port=5000):
        self.server_host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port

        self.client_id = None
        self.room_id = None

        self.tcp_sock = None
        self.udp_sock = None

        self.processor = FrameProcessor()
        self.reassembler = FrameReassembler()
        self.stop_event = threading.Event()

    def connect(self):
        """Establish TCP signaling connection and get client ID."""
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.settimeout(TCP_CONNECT_TIMEOUT)
            self.tcp_sock.connect((self.server_host, self.tcp_port))

            # 1. Receive LOGIN confirmation
            msg_type, payload = recv_message(self.tcp_sock)
            if msg_type == PacketType.LOGIN:
                self.client_id = payload.get("client_id")
                logging.info(f"Logged in as Client ID: {self.client_id}")

                # Restore TCP socket to blocking mode for later signaling
                self.tcp_sock.settimeout(None)
                return True
            else:
                logging.error(f"Failed to login. Expected LOGIN, got {msg_type}")
        except socket.timeout:
            logging.error(f"TCP Connection timed out after {TCP_CONNECT_TIMEOUT} seconds to {self.server_host}:{self.tcp_port}")
        except Exception as e:
            logging.error(f"TCP Connection error: {e}")
        return False

    def join_room(self, room_id):
        """Join a specific room via TCP."""
        try:
            send_message(self.tcp_sock, PacketType.JOIN_ROOM, {"room_id": room_id})
            msg_type, payload = recv_message(self.tcp_sock)

            if msg_type == PacketType.ROOM_STATE:
                self.room_id = int(room_id)
                logging.info(f"Joined Room: {self.room_id}. Current participants: {payload.get('participants')}")
                return True
            elif msg_type == PacketType.ERROR:
                logging.error(f"Join Room failed: {payload.get('reason')}")
        except Exception as e:
            logging.error(f"Join Room error: {e}")
        return False

    def start_udp(self):
        """Initialize UDP socket for streaming."""
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind to 0 to let OS pick port
        self.udp_sock.bind(('0.0.0.0', 0))
        # Small timeout so receive loop can check stop_event periodically
        self.udp_sock.settimeout(1.0)

    def sender_loop(self):
        """Background thread to capture and send video chunks."""
        frame_id = 0
        server_udp_addr = (self.server_host, self.udp_port)

        logging.info("Starting UDP Sender loop...")
        while not self.stop_event.is_set():
            try:
                compressed_bytes = self.processor.capture_and_compress()
            except Exception as e:
                logging.error(f"Capture error: {e}")
                compressed_bytes = None

            if compressed_bytes:
                # Use protocol to chunk the frame
                chunks = chunk_frame(self.client_id, self.room_id, frame_id, compressed_bytes)
                for chunk in chunks:
                    try:
                        self.udp_sock.sendto(chunk, server_udp_addr)
                    except Exception as e:
                        logging.error(f"UDP Send error: {e}")
                        break
                frame_id += 1

    def run(self, room_id=1, gui_window=None):
        """Main loop to receive UDP chunks and dispatch frames to the GUI.

        gui_window: optional MainWindow instance. If provided, frames are sent
        into the GUI via its update_network_frame() API (thread-safe signal).
        """
        try:
            if not self.connect():
                return

            if not self.join_room(room_id):
                return

            self.start_udp()

            # Start sender thread
            sender_thread = threading.Thread(target=self.sender_loop, daemon=True)
            sender_thread.start()

            logging.info("Streaming started. (GUI integrated: %s)" % (gui_window is not None))

            while not self.stop_event.is_set():
                try:
                    # Receive UDP chunks (with socket timeout so we can react to stop_event)
                    try:
                        data, _ = self.udp_sock.recvfrom(65535)
                    except socket.timeout:
                        continue

                    if not data:
                        continue

                    unpacked = unpack_udp_chunk(data)
                    if unpacked:
                        sender_id, room_id, f_id, c_idx, t_chunks, payload = unpacked

                        # Feed into reassembler
                        full_frame_bytes = self.reassembler.add_chunk(sender_id, f_id, c_idx, t_chunks, payload)

                        if full_frame_bytes:
                            frame = self.processor.decompress_to_frame(full_frame_bytes)
                            if frame is not None:
                                # Dispatch to GUI if available; otherwise log at debug level
                                if gui_window is not None:
                                    try:
                                        gui_window.update_network_frame(sender_id, frame)
                                    except Exception as e:
                                        logging.error(f"Failed to update GUI frame: {e}")
                                else:
                                    logging.debug("Received frame for client %s but no GUI attached", sender_id)

                except Exception as e:
                    logging.error(f"Connection error: {e}")
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def cleanup(self):
        logging.info("Cleaning up...")
        self.stop_event.set()
        if self.tcp_sock:
            try:
                send_message(self.tcp_sock, PacketType.LEAVE_ROOM, {"room_id": self.room_id})
                self.tcp_sock.close()
            except:
                pass
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except:
                pass
        try:
            self.processor.cleanup()
        except:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Integrated Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP")
    parser.add_argument("--tcp", type=int, default=8000, help="Server TCP port")
    parser.add_argument("--udp", type=int, default=5000, help="Server UDP port")
    parser.add_argument("--room", type=int, default=1, help="Room ID (integer) to join")
    args = parser.parse_args()

    client = HexaClient(args.host, args.tcp, args.udp)

    # Try to integrate with PyQt GUI. If PyQt is not available, fall back to headless mode
    try:
        from PyQt6.QtWidgets import QApplication
        from Code.client.gui.main_window import MainWindow

        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()

        # Run client in background thread so GUI event loop remains responsive
        client_thread = threading.Thread(target=client.run, args=(args.room, window), daemon=True)
        client_thread.start()

        exit_code = app.exec()

        # Ensure cleanup on exit
        client.cleanup()
        sys.exit(exit_code)

    except Exception as e:
        logging.warning(f"PyQt GUI not available or failed to start ({e}). Running in headless mode.")
        # Run blocking (headless) mode without GUI. The run() will not display frames; it's intended for testing.
        client.run(args.room)
