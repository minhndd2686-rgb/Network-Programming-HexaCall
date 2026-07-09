import socket
import threading
import logging
import sys
import os
import argparse
import time
from collections import deque
from typing import Optional, Dict
import numpy as np

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Code.client.media.frame_processor import FrameProcessor
from Code.client.media.audio_processor import AudioProcessor, PYAUDIO_AVAILABLE
from Code.shared.protocol import (
    recv_message, send_message, PacketType,
    chunk_frame, unpack_udp_chunk, FrameReassembler,
    AUDIO_BYTES_PER_FRAME, AUDIO_FRAME_MS
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Timeout (seconds) for initial TCP connect + LOGIN handshake.
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
        self.gui_window = None

        # Audio/Video state gates
        self.camera_on = threading.Event()
        self.camera_on.set()          # Camera on by default
        self.mic_muted = threading.Event()  # Clear = unmuted by default

        # Audio processor (None if PyAudio unavailable)
        self.audio_processor: Optional[AudioProcessor] = None
        if PYAUDIO_AVAILABLE:
            try:
                self.audio_processor = AudioProcessor()
                logging.info("AudioProcessor initialized successfully")
            except Exception as e:
                logging.warning(f"Failed to initialize AudioProcessor: {e}")

        # Per-sender audio jitter buffers (sender_id -> deque of PCM frames)
        self._sender_audio_buffers: Dict[int, deque] = {}
        self._audio_lock = threading.Lock()
        self._audio_playback_thread: Optional[threading.Thread] = None

        # Audio sender thread and frame counter
        self._audio_sender_thread: Optional[threading.Thread] = None
        self.audio_frame_id = 0

        # TCP listener thread reference (stored so cleanup can see it)
        self.tcp_listener_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Connection & room
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish TCP signaling connection and receive client ID from server."""
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.settimeout(TCP_CONNECT_TIMEOUT)
            self.tcp_sock.connect((self.server_host, self.tcp_port))

            msg_type, payload = recv_message(self.tcp_sock)
            if msg_type == PacketType.LOGIN and payload is not None:
                self.client_id = payload.get("client_id")
                if self.client_id is None:
                    logging.error("LOGIN payload missing client_id")
                else:
                    logging.info(f"Logged in as Client ID: {self.client_id}")
                self.tcp_sock.settimeout(None)
                return True
            else:
                logging.error(f"Failed to login. Expected LOGIN, got {msg_type}")
        except socket.timeout:
            logging.error(
                f"TCP Connection timed out after {TCP_CONNECT_TIMEOUT}s "
                f"to {self.server_host}:{self.tcp_port}"
            )
        except Exception as e:
            logging.error(f"TCP Connection error: {e}")
        return False

    def join_room(self, room_id) -> bool:
        """Join a specific room via TCP signaling."""
        try:
            send_message(self.tcp_sock, PacketType.JOIN_ROOM, {"room_id": room_id})
            msg_type, payload = recv_message(self.tcp_sock)

            if msg_type == PacketType.ROOM_STATE:
                self.room_id = int(room_id)
                logging.info(
                    f"Joined Room: {self.room_id}. "
                    f"Participants: {payload.get('participants')}"
                )
                return True
            elif msg_type == PacketType.ERROR:
                logging.error(f"Join Room failed: {payload.get('reason')}")
        except Exception as e:
            logging.error(f"Join Room error: {e}")
        return False

    def start_udp(self):
        """Initialize UDP socket for media streaming."""
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.bind(('0.0.0.0', 0))
        # 1s timeout allows stop_event to be checked without busy-wait
        self.udp_sock.settimeout(1.0)

    # ------------------------------------------------------------------
    # Audio sender
    # ------------------------------------------------------------------

    def _audio_sender_loop(self):
        """Dedicated thread: capture microphone at 50 Hz and send via UDP."""
        logging.info("[AUDIO] Audio sender thread started")

        while not self.stop_event.is_set():
            start_time = time.time()

            # Only send if mic is unmuted and capture stream is active
            if (not self.mic_muted.is_set()
                    and self.audio_processor
                    and self.audio_processor.capture_active):
                try:
                    audio_bytes = self.audio_processor.read_frame()

                    if audio_bytes and self.client_id is not None and self.room_id is not None:
                        chunks = chunk_frame(
                            self.client_id,
                            self.room_id,
                            self.audio_frame_id,
                            audio_bytes,
                            PacketType.AUDIO_DATA
                        )
                        for chunk in chunks:
                            try:
                                self.udp_sock.sendto(chunk, (self.server_host, self.udp_port))
                            except Exception as e:
                                logging.error(f"[AUDIO] Send error: {e}")
                                break
                        self.audio_frame_id += 1
                except Exception as e:
                    logging.error(f"[AUDIO] Capture error: {e}")

            # Maintain 50 Hz cadence (20 ms interval)
            elapsed = time.time() - start_time
            time.sleep(max(0.0, 0.02 - elapsed))

    # ------------------------------------------------------------------
    # Video sender
    # ------------------------------------------------------------------

    def sender_loop(self):
        """Video capture and transmission loop at ~30 FPS."""
        logging.info("[VIDEO] Video sender loop started")
        video_frame_id = 0

        while not self.stop_event.is_set():
            start_time = time.time()

            if self.camera_on.is_set():
                result = self.processor.capture_and_compress(return_frame=True)
                compressed_bytes, raw_frame = result if isinstance(result, tuple) else (result, None)

                has_raw_frame = raw_frame is not None
                if isinstance(raw_frame, np.ndarray):
                    has_raw_frame = raw_frame.size > 0

                if compressed_bytes and self.client_id and self.room_id and self.udp_sock:
                    chunks = chunk_frame(
                        self.client_id,
                        self.room_id,
                        video_frame_id,
                        compressed_bytes,
                        PacketType.VIDEO_DATA
                    )
                    for chunk in chunks:
                        try:
                            self.udp_sock.sendto(chunk, (self.server_host, self.udp_port))
                        except Exception as e:
                            logging.error(f"[VIDEO] Send error: {e}")
                            break
                    video_frame_id += 1

                # Local preview via GUI signal (thread-safe)
                if has_raw_frame and self.gui_window is not None and self.client_id is not None:
                    try:
                        self.gui_window.update_network_frame(self.client_id, raw_frame)
                    except Exception as e:
                        logging.error(f"[VIDEO] Preview error: {e}")

            # Maintain 30 FPS cadence (33 ms interval)
            elapsed = time.time() - start_time
            time.sleep(max(0.0, 0.033 - elapsed))

    # ------------------------------------------------------------------
    # Main run loop (UDP receive + dispatch)
    # ------------------------------------------------------------------

    def run(self, room_id=1, gui_window=None):
        """Connect, join room, start threads, then receive UDP media until stopped."""
        try:
            if not self.connect():
                return

            if not self.join_room(room_id):
                return

            self.start_udp()

            # Store gui_window before starting threads so local preview works immediately
            self.gui_window = gui_window

            # --- Video sender thread ---
            sender_thread = threading.Thread(target=self.sender_loop, daemon=True)
            sender_thread.start()

            # --- TCP listener thread (ROOM_STATE broadcasts) ---
            self.tcp_listener_thread = threading.Thread(
                target=self._tcp_listener_loop, daemon=True
            )
            self.tcp_listener_thread.start()

            # --- Audio capture + sender thread ---
            if self.audio_processor:
                # FIX: start_capture() was never called before → capture_active was
                # always False → _audio_sender_loop silently skipped every frame.
                if self.audio_processor.start_capture():
                    logging.info("[AUDIO] Microphone capture started")
                else:
                    logging.warning("[AUDIO] Failed to start microphone capture")

                self._audio_sender_thread = threading.Thread(
                    target=self._audio_sender_loop,
                    name="AudioSender",
                    daemon=True
                )
                self._audio_sender_thread.start()
                logging.info("[AUDIO] Audio sender thread launched")

            # --- Audio playback thread ---
            if self.audio_processor:
                if self.audio_processor.start_playback():
                    self._audio_playback_thread = threading.Thread(
                        target=self._audio_playback_loop,
                        name="AudioPlayback",
                        daemon=True
                    )
                    self._audio_playback_thread.start()
                    logging.info("[AUDIO] Audio playback thread launched")
                else:
                    logging.warning("[AUDIO] Failed to start audio playback")

            logging.info("Streaming started. (GUI: %s)", gui_window is not None)

            # --- UDP receive loop ---
            while not self.stop_event.is_set():
                try:
                    try:
                        data, _ = self.udp_sock.recvfrom(65535)
                    except socket.timeout:
                        continue

                    if not data:
                        continue

                    # unpack_udp_chunk now returns 7-tuple including pkt_type
                    unpacked = unpack_udp_chunk(data)
                    if not unpacked:
                        continue

                    sender_id, _room_id, f_id, c_idx, t_chunks, pkt_type, payload = unpacked

                    # Reassembler stores pkt_type per frame; returns (bytes, pkt_type) when complete
                    result = self.reassembler.add_chunk(
                        sender_id, f_id, c_idx, t_chunks, payload, pkt_type
                    )
                    if not result:
                        continue

                    full_frame_bytes, real_pkt_type = result

                    if real_pkt_type == PacketType.VIDEO_DATA:
                        frame = self.processor.decompress_to_frame(full_frame_bytes)
                        if frame is not None and gui_window is not None:
                            try:
                                gui_window.update_network_frame(sender_id, frame)
                            except Exception as e:
                                logging.error(f"[VIDEO] GUI update error: {e}")

                    elif real_pkt_type == PacketType.AUDIO_DATA:
                        with self._audio_lock:
                            if sender_id not in self._sender_audio_buffers:
                                # ~160 ms jitter buffer per remote sender
                                self._sender_audio_buffers[sender_id] = deque(maxlen=8)
                            self._sender_audio_buffers[sender_id].append(full_frame_bytes)

                    else:
                        logging.debug("[UDP] Unknown packet type: %d", real_pkt_type)

                except Exception as e:
                    logging.error(f"[UDP] Receive error: {e}")
                    break

        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    # ------------------------------------------------------------------
    # Audio mixing & playback
    # ------------------------------------------------------------------

    def _mix_audio_frames(self) -> Optional[bytes]:
        """
        Mix the latest PCM frame from each remote sender into one output frame.
        Skips own audio to prevent echo. Returns None when nothing to play.
        """
        with self._audio_lock:
            if not self._sender_audio_buffers:
                return None

            sender_frames = []
            stale_senders = []

            for sender_id, buf in self._sender_audio_buffers.items():
                if sender_id == self.client_id:
                    continue  # Skip own audio (echo prevention)
                if buf:
                    # Pop latest frame; older frames are silently dropped
                    frame_bytes = buf.pop()
                    frame = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.int32)
                    sender_frames.append(frame)
                else:
                    stale_senders.append(sender_id)

            for sid in stale_senders:
                del self._sender_audio_buffers[sid]

            if not sender_frames:
                return None

            # Average mix (prevents clipping when multiple people speak)
            mixed = sum(sender_frames) // len(sender_frames)
            mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
            return mixed.tobytes()

    def _audio_playback_loop(self):
        """Background thread: mix remote audio and push to speaker every 20 ms."""
        logging.info("[AUDIO] Playback loop started")
        frame_interval = AUDIO_FRAME_MS / 1000.0
        last_frame_time = time.time()

        while not self.stop_event.is_set():
            try:
                now = time.time()
                elapsed = now - last_frame_time

                if elapsed >= frame_interval:
                    mixed_audio = self._mix_audio_frames()
                    if mixed_audio is not None and self.audio_processor:
                        self.audio_processor.play_frame(mixed_audio)
                    last_frame_time = now
                else:
                    time.sleep(max(0.0, frame_interval - elapsed))

            except Exception as e:
                logging.error(f"[AUDIO] Playback loop error: {e}")
                time.sleep(0.1)

        logging.info("[AUDIO] Playback loop exited")

    # ------------------------------------------------------------------
    # TCP listener (ROOM_STATE broadcasts)
    # ------------------------------------------------------------------

    def _tcp_listener_loop(self):
        """Background thread: handle ROOM_STATE and ERROR messages from server."""
        logging.info("TCP listener loop started")

        while not self.stop_event.is_set():
            try:
                msg_type, payload = recv_message(self.tcp_sock)

                if msg_type is None:
                    logging.warning("TCP connection closed by server")
                    break

                if msg_type == PacketType.ROOM_STATE:
                    participants = payload.get("participants", [])
                    current_ids = set()

                    for p in participants:
                        try:
                            cid = p.get("client_id")
                            if cid is None:
                                continue
                            current_ids.add(cid)

                            if self.gui_window:
                                slot_id = self.gui_window.client_slots.get(cid)
                                if slot_id:
                                    frame_widget = self.gui_window.video_frames.get(slot_id)
                                    if frame_widget:
                                        frame_widget.set_camera_on(p.get("camera_on", True))
                                        frame_widget.set_mic_muted(p.get("mic_muted", False))
                        except Exception as e:
                            logging.error(f"ROOM_STATE participant update error: {e}")

                    # Detect disconnected participants and notify GUI via signal
                    if self.gui_window:
                        previous_ids = set(self.gui_window.client_slots.keys())
                        disconnected_ids = previous_ids - current_ids
                        # Never treat ourselves as disconnected
                        disconnected_ids.discard(self.client_id)

                        for sid in disconnected_ids:
                            # emit signal → handle_disconnect_slot runs on GUI thread
                            self.gui_window.remove_participant_widget(sid)

                    # Clean up audio jitter buffers for departed senders
                    with self._audio_lock:
                        for sid in list(self._sender_audio_buffers.keys()):
                            if sid not in current_ids and sid != self.client_id:
                                del self._sender_audio_buffers[sid]
                                logging.debug(
                                    "[AUDIO] Removed buffer for disconnected client %d", sid
                                )

                elif msg_type == PacketType.ERROR:
                    logging.warning(f"Server error: {payload.get('reason')}")

            except Exception as e:
                logging.error(f"TCP listener error: {e}")
                break

        logging.info("TCP listener loop exited")

    # ------------------------------------------------------------------
    # State updates (camera / mic)
    # ------------------------------------------------------------------

    def set_camera_on(self, enabled: bool):
        """Toggle camera capture and notify server."""
        if enabled:
            self.camera_on.set()
        else:
            self.camera_on.clear()
        self._send_state_update()

    def set_mic_muted(self, muted: bool):
        """Toggle mic mute state and notify server."""
        if muted:
            self.mic_muted.set()
        else:
            self.mic_muted.clear()
        self._send_state_update()

    def _send_state_update(self):
        """Send camera/mic state to server via TCP ROOM_STATE message."""
        if not self.tcp_sock or self.room_id is None or self.client_id is None:
            return
        try:
            send_message(self.tcp_sock, PacketType.ROOM_STATE, {
                "room_id": self.room_id,
                "client_id": self.client_id,
                "camera_on": self.camera_on.is_set(),
                "mic_muted": self.mic_muted.is_set(),
            })
        except Exception as e:
            logging.error(f"Failed to send state update: {e}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _remove_sender_buffer(self, sender_id: int):
        """Remove audio jitter buffer for a departed sender."""
        with self._audio_lock:
            self._sender_audio_buffers.pop(sender_id, None)

    def cleanup(self):
        """Stop all threads, release audio/video resources, close sockets."""
        logging.info("Cleaning up HexaClient...")
        self.stop_event.set()

        # Stop audio capture + playback first (closes PyAudio streams)
        if self.audio_processor:
            try:
                self.audio_processor.cleanup()
                logging.info("[AUDIO] AudioProcessor cleaned up")
            except Exception as e:
                logging.error(f"AudioProcessor cleanup error: {e}")
            self.audio_processor = None

        # Join audio threads
        for thread, name in [
            (self._audio_sender_thread, "AudioSender"),
            (self._audio_playback_thread, "AudioPlayback"),
        ]:
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
                logging.debug("[AUDIO] %s thread joined", name)

        self._audio_sender_thread = None
        self._audio_playback_thread = None

        # Discard all audio buffers
        with self._audio_lock:
            self._sender_audio_buffers.clear()

        # Send LEAVE_ROOM before closing TCP socket
        if self.tcp_sock and self.room_id:
            try:
                send_message(self.tcp_sock, PacketType.LEAVE_ROOM, {"room_id": self.room_id})
            except Exception:
                pass

        # Close sockets
        for sock, name in [(self.tcp_sock, "TCP"), (self.udp_sock, "UDP")]:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self.tcp_sock = None
        self.udp_sock = None

        # Release camera
        try:
            self.processor.cleanup()
        except Exception:
            pass

        logging.info("HexaClient cleanup complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HexaCall Integrated Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP")
    parser.add_argument("--tcp", type=int, default=8000, help="Server TCP port")
    parser.add_argument("--udp", type=int, default=5000, help="Server UDP port")
    parser.add_argument("--room", type=int, default=1, help="Room ID to join")
    args = parser.parse_args()

    try:
        from PyQt6.QtWidgets import QApplication
        from Code.client.gui.login import LoginWindow
        from Code.client.gui.main_window import MainWindow

        app = QApplication(sys.argv)
        login_window = LoginWindow()

        def on_login_connect(username, server_ip, port, room_id):
            login_window.close()
            gui_client = HexaClient(server_ip, port, udp_port=5000)
            window = MainWindow()
            window.set_client(gui_client)
            window.show()

            client_thread = threading.Thread(
                target=gui_client.run,
                args=(room_id, window),
                daemon=True
            )
            client_thread.start()
            app.client = gui_client

        login_window.connect_requested.connect(on_login_connect)
        login_window.show()

        exit_code = app.exec()
        if hasattr(app, 'client'):
            app.client.cleanup()
        sys.exit(exit_code)

    except Exception as e:
        logging.warning(
            f"PyQt GUI not available or failed ({e}). Running headless."
        )
        headless_client = HexaClient(args.host, args.tcp, args.udp)
        headless_client.run(args.room)
