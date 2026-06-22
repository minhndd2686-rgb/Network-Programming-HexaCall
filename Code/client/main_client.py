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

        # Optional callbacks for GUI integration
        # If set, these will be called instead of using cv2
        self.frame_callback = None  # Called with (sender_id, frame)
        self.error_callback = None  # Called with (error_msg)
        self.disconnect_callback = None  # Called with (client_id)

    def connect(self):
        """Establish TCP signaling connection and get client ID."""
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # Socket tuning for low-latency signaling
            self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            # Set timeout to prevent indefinite blocking
            self.tcp_sock.settimeout(5.0)
            
            logging.info(f"Connecting to TCP server {self.server_host}:{self.tcp_port}...")
            self.tcp_sock.connect((self.server_host, self.tcp_port))
            logging.info(f"TCP connection established")

            # 1. Receive LOGIN confirmation
            msg_type, payload = recv_message(self.tcp_sock, timeout=5.0)
            if msg_type == PacketType.LOGIN:
                self.client_id = payload.get("client_id")
                logging.info(f"Logged in as Client ID: {self.client_id}")
                return True
            else:
                logging.error(f"Failed to login. Expected LOGIN, got {msg_type}")
                return False
        except socket.timeout:
            logging.error(f"TCP connection timeout after 5 seconds")
            return False
        except Exception as e:
            logging.error(f"TCP Connection error: {e}")
        return False

    def join_room(self, room_id):
        """Join a specific room via TCP."""
        try:
            send_message(self.tcp_sock, PacketType.JOIN_ROOM, {"room_id": room_id})
            msg_type, payload = recv_message(self.tcp_sock, timeout=5.0)

            if msg_type == PacketType.ROOM_STATE:
                self.room_id = room_id
                participants = payload.get('participants', [])
                logging.info(f"Joined Room: {room_id}. Participants: {len(participants)}")
                return True
            elif msg_type == PacketType.ERROR:
                logging.error(f"Join Room failed: {payload.get('reason')}")
            else:
                logging.error(f"Expected ROOM_STATE, got {msg_type}")
            return False
        except socket.timeout:
            logging.error(f"Join room timeout after 5 seconds")
            return False
        except Exception as e:
            logging.error(f"Join Room error: {e}")
        return False

    def start_udp(self):
        """Initialize UDP socket for streaming."""
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Set socket timeout to prevent indefinite blocking
        # Bind to 0 to let OS pick port
        self.udp_sock.bind(('0.0.0.0', 0))
        self.udp_sock.settimeout(2.0)  # 2 second timeout for UDP
        
        logging.info(f"UDP socket bound to {self.udp_sock.getsockname()}")

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
            if self.error_callback:
                self.error_callback("Failed to connect to server")
            return

        if not self.join_room(room_id):
            if self.error_callback:
                self.error_callback("Failed to join room")
            return

        self.start_udp()

        # Start sender thread
        sender_thread = threading.Thread(target=self.sender_loop, daemon=True)
        sender_thread.start()

        logging.info("Streaming started. Press 'q' to quit.")

        try:
            while not self.stop_event.is_set():
                try:
                    # Receive UDP chunks (timeout: 2.0s)
                    data, addr = self.udp_sock.recvfrom(65535)
                    if not data:
                        continue
                
                except socket.timeout:
                    # Timeout is normal (no frames arriving)
                    # Check stop_event and continue
                    continue
                    
                except socket.error as e:
                    # Network error - notify callback and break
                    if self.error_callback:
                        self.error_callback(f"UDP receive error: {e}")
                    break

                unpacked = unpack_udp_chunk(data)
                if unpacked:
                    sender_id, room_id, f_id, c_idx, t_chunks, payload = unpacked

                    # Feed into reassembler
                    full_frame_bytes = self.reassembler.add_chunk(
                        sender_id, f_id, c_idx, t_chunks, payload
                    )

                    if full_frame_bytes:
                        frame = self.processor.decompress_to_frame(full_frame_bytes)
                        if frame is not None:
                            # Route frame to callback (if GUI is using this)
                            # or to cv2.imshow (if running standalone CLI)
                            if self.frame_callback:
                                try:
                                    self.frame_callback(sender_id, frame)
                                except Exception as e:
                                    logging.error(f"Frame callback error: {e}")
                            else:
                                window_name = f"HexaCall - Room {self.room_id} (Client {sender_id})"
                                cv2.imshow(window_name, frame)

                # Only wait for 'q' key if not using callback (CLI mode)
                if not self.frame_callback:
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
        except KeyboardInterrupt:
            logging.info("Received KeyboardInterrupt")
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
    parser.add_argument("--host", default="192.168.11.1", help="Server IP")
    parser.add_argument("--tcp", type=int, default=8000, help="Server TCP port")
    parser.add_argument("--udp", type=int, default=5000, help="Server UDP port")
    parser.add_argument("--room", default="room1", help="Room to join")
    args = parser.parse_args()

    client = HexaClient(args.host, args.tcp, args.udp)
    client.run()
