import socket
import threading
import cv2
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
            self.tcp_sock.connect((self.server_host, self.tcp_port))

            # 1. Receive LOGIN confirmation
            msg_type, payload = recv_message(self.tcp_sock)
            if msg_type == PacketType.LOGIN:
                self.client_id = payload.get("client_id")
                logging.info(f"Logged in as Client ID: {self.client_id}")
                return True
            else:
                logging.error(f"Failed to login. Expected LOGIN, got {msg_type}")
        except Exception as e:
            logging.error(f"TCP Connection error: {e}")
        return False

    def join_room(self, room_id):
        """Join a specific room via TCP."""
        try:
            send_message(self.tcp_sock, PacketType.JOIN_ROOM, {"room_id": room_id})
            msg_type, payload = recv_message(self.tcp_sock)

            if msg_type == PacketType.ROOM_STATE:
                self.room_id = room_id
                logging.info(f"Joined Room: {room_id}. Current participants: {payload.get('participants')}")
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

    def sender_loop(self):
        """Background thread to capture and send video chunks."""
        frame_id = 0
        server_udp_addr = (self.server_host, self.udp_port)

        logging.info("Starting UDP Sender loop...")
        while not self.stop_event.is_set():
            compressed_bytes = self.processor.capture_and_compress()
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

    def run(self, room_id=1):
        """Main loop to receive UDP chunks and render."""
        if not self.connect():
            return

        if not self.join_room(room_id):
            return

        self.start_udp()

        # Start sender thread
        sender_thread = threading.Thread(target=self.sender_loop, daemon=True)
        sender_thread.start()

        logging.info("Streaming started. Press 'q' to quit.")

        try:
            while not self.stop_event.is_set():
                # Receive UDP chunks
                data, _ = self.udp_sock.recvfrom(65535)
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
                            window_name = f"HexaCall - Room {self.room_id} (Client {sender_id})"
                            cv2.imshow(window_name, frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
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
            self.udp_sock.close()
        self.processor.cleanup()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Integrated Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP")
    parser.add_argument("--tcp", type=int, default=8000, help="Server TCP port")
    parser.add_argument("--udp", type=int, default=5000, help="Server UDP port")
    parser.add_argument("--room", type=int, default=1, help="Room ID (integer)")
    args = parser.parse_args()

    client = HexaClient(args.host, args.tcp, args.udp)
    client.run(args.room)
