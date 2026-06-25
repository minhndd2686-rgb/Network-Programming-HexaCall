import socket
import threading
import logging
import sys
import os
import time

# Add path to import shared module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from Code.shared.protocol import chunk_frame, unpack_udp_chunk, FrameReassembler
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from Code.shared.protocol import chunk_frame, unpack_udp_chunk, FrameReassembler

class UdpStreamer:
    """
    UdpStreamer manages sending and receiving video frames over UDP. It supports chunking large frames and reassembling them when received.
    """
    def __init__(self, server_host, server_port, client_id, room_id, frame_processor):
        self.server_addr = (server_host, server_port)
        self.client_id = int(client_id)
        self.room_id = int(room_id)
        self.processor = frame_processor

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind to ephemeral port
        self.sock.bind(('0.0.0.0', 0))

        self.reassembler = FrameReassembler(timeout=0.5)
        self._stop_event = threading.Event()
        self.frame_callback = None # function(sender_id, frame)

        self.logger = logging.getLogger("UdpStreamer")
        self.send_thread = None
        self.recv_thread = None

        self.current_frame_id = 0

    def set_frame_callback(self, callback):
        """The callback will be triggered when a complete frame is received."""
        self.frame_callback = callback

    def start(self):
        """Launch worker threads for sending/receiving video."""
        self._stop_event.clear()

        # Recv thread
        self.recv_thread = threading.Thread(target=self._receive_loop, name="UdpRecvThread", daemon=True)
        self.recv_thread.start()

        # Send thread
        self.send_thread = threading.Thread(target=self._send_loop, name="UdpSendThread", daemon=True)
        self.send_thread.start()

        self.logger.info(f"UdpStreamer started. Sending to {self.server_addr}")

    def stop(self):
        """Stop the threads and close the socket."""
        self.logger.info("Stopping UdpStreamer...")
        self._stop_event.set()

        if self.send_thread:
            self.send_thread.join(timeout=1.0)
        if self.recv_thread:
            self.recv_thread.join(timeout=1.0)

        self.sock.close()
        self.logger.info("UdpStreamer stopped.")

    def _send_loop(self):
        """Camera capture loop, compressing and sending chunks."""
        while not self._stop_event.is_set():
            try:
                frame_bytes = self.processor.capture_and_compress()
                if not frame_bytes:
                    time.sleep(0.01)
                    continue

                # Chunk frame
                self.current_frame_id = (self.current_frame_id + 1) % 1000000
                packets = chunk_frame(
                    self.client_id,
                    self.room_id,
                    self.current_frame_id,
                    frame_bytes
                )

                for p in packets:
                    self.sock.sendto(p, self.server_addr)

                # Cân bằng frame rate (khoảng 20-30 FPS)
                time.sleep(0.03)

            except Exception as e:
                if not self._stop_event.is_set():
                    self.logger.error(f"UDP send error: {e}")
                time.sleep(0.1)

    def _receive_loop(self):
        """Loop that receives chunks, reassembles, and decodes."""
        self.sock.settimeout(1.0)
        while not self._stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue

                unpacked = unpack_udp_chunk(data)
                if not unpacked:
                    continue

                sender_id, room_id, frame_id, c_idx, t_chunks, payload = unpacked

                # Reassemble
                full_frame_bytes = self.reassembler.add_chunk(
                    sender_id, frame_id, c_idx, t_chunks, payload
                )

                if full_frame_bytes and self.frame_callback:
                    # Decode to OpenCV frame
                    frame = self.processor.decompress_to_frame(full_frame_bytes)
                    if frame is not None:
                        self.frame_callback(sender_id, frame)

            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    self.logger.error(f"UDP receive error: {e}")
