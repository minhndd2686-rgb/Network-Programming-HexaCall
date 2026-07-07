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
        self.gui_window = None

        # Audio/Video state gates
        self.camera_on = threading.Event()
        self.camera_on.set()  # Camera on by default
        self.mic_muted = threading.Event()  # Mic unmuted by default

        # Audio processor (None if PyAudio unavailable)
        self.audio_processor: Optional[AudioProcessor] = None
        if PYAUDIO_AVAILABLE:
            try:
                self.audio_processor = AudioProcessor()
                logging.info("AudioProcessor initialized successfully")
            except Exception as e:
                logging.warning(f"Failed to initialize AudioProcessor: {e}")

        # Per-sender audio jitter buffers to prevent stream interleaving
        # sender_id -> deque(max 8 frames ≈ 160ms buffer per user)
        self._sender_audio_buffers: Dict[int, deque] = {}
        self._audio_lock = threading.Lock()
        self._audio_playback_thread: Optional[threading.Thread] = None

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
        """Background thread to capture, locally preview, and send video/audio chunks."""
        video_frame_id = 0
        audio_frame_id = 0
        server_udp_addr = (self.server_host, self.udp_port)

        logging.info("Starting UDP Sender loop (video+audio)...")

        # Audio preparation
        if self.audio_processor:
            if not self.audio_processor.start_capture():
                logging.warning("Failed to start audio capture - microphone disabled")
                self.audio_processor = None

        while not self.stop_event.is_set():
            try:
                # === VIDEO: Capture and send if camera is on ===
                start_time = time.time()
                if self.camera_on.is_set():
                    result = self.processor.capture_and_compress(return_frame=True)
                else:
                    result = (None, None)


                compressed_bytes, raw_frame = result if isinstance(result, tuple) else (result, None)

                if (
                    compressed_bytes
                    and self.client_id is not None
                    and self.room_id is not None
                    and self.udp_sock is not None
                ):
                    # Use protocol to chunk the frame
                    chunks = chunk_frame(self.client_id, self.room_id, video_frame_id, compressed_bytes)
                    for chunk in chunks:
                        try:
                            self.udp_sock.sendto(chunk, server_udp_addr)
                        except Exception as e:
                            logging.error(f"UDP Send error: {e}")
                            break
                    video_frame_id += 1

                # Local preview: reuse the raw frame captured above.
                if (
                    raw_frame is not None
                    and self.gui_window is not None
                    and self.client_id is not None
                ):
                    try:
                        self.gui_window.update_network_frame(self.client_id, raw_frame)
                    except Exception as e:
                        logging.error(f"Failed to update local preview: {e}")

                # === AUDIO: Capture and send if mic not muted ===
                if (
                    not self.mic_muted.is_set()
                    and self.audio_processor is not None
                    and self.audio_processor.capture_active
                    and self.client_id is not None
                    and self.room_id is not None
                    and self.udp_sock is not None
                ):
                    audio_bytes = self.audio_processor.read_frame()
                    if audio_bytes:
                        # Audio frame is small enough to not need chunking (640 bytes)
                        # Use same chunk_frame function with PacketType.AUDIO_DATA
                        chunks = chunk_frame(self.client_id, self.room_id, audio_frame_id, audio_bytes, PacketType.AUDIO_DATA)
                        for chunk in chunks:
                            try:
                                self.udp_sock.sendto(chunk, server_udp_addr)
                            except Exception as e:
                                logging.error(f"Audio UDP send error: {e}")
                                break
                        audio_frame_id += 1

            except Exception as e:
                logging.error(f"Sender loop error: {e}")

            # Dynamic sleep to maintain ~30 FPS and avoid server overload
            elapsed = time.time() - start_time
            sleep_time = max(0, 0.033 - elapsed)
            time.sleep(sleep_time)

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

            # Store gui_window reference before sender_loop starts so local preview is available immediately.
            self.gui_window = gui_window

            # Start sender thread
            sender_thread = threading.Thread(target=self.sender_loop, daemon=True)
            sender_thread.start()

            # Start TCP listener thread for ROOM_STATE updates
            self.tcp_listener_thread = threading.Thread(target=self._tcp_listener_loop, daemon=True)
            self.tcp_listener_thread.start()

            if self.audio_processor:
                if self.audio_processor.start_playback():
                    self._audio_playback_thread = threading.Thread(
                        target=self._audio_playback_loop,
                        name="AudioPlayback",
                        daemon=True
                    )
                    self._audio_playback_thread.start()
                    logging.info("Audio playback thread started")
                else:
                    logging.warning("Failed to start audio playback")

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
                            # Determine packet type from header (byte 5)
                            pkt_type = data[5] if len(data) > 5 else PacketType.VIDEO_DATA

                            if pkt_type == PacketType.VIDEO_DATA:
                                # Video frame
                                frame = self.processor.decompress_to_frame(full_frame_bytes)
                                if frame is not None:
                                    # Dispatch to GUI if available
                                    if gui_window is not None:
                                        try:
                                            gui_window.update_network_frame(sender_id, frame)
                                        except Exception as e:
                                            logging.error(f"Failed to update GUI frame: {e}")
                                    else:
                                        logging.debug("Received frame for client %s but no GUI attached", sender_id)

                            elif pkt_type == PacketType.AUDIO_DATA:
                                # Audio frame - put into per-sender jitter buffer for playback
                                with self._audio_lock:
                                    if sender_id not in self._sender_audio_buffers:
                                        self._sender_audio_buffers[sender_id] = deque(maxlen=8)  # ~160ms buffer per sender
                                    self._sender_audio_buffers[sender_id].append(full_frame_bytes)
                                # Signal GUI to update mic status if needed
                                # (handled by ROOM_STATE from server)
                            else:
                                logging.debug("Unknown packet type: %d", pkt_type)

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

        # Stop audio processor explicitly (closes PyAudio streams/threads)
        if self.audio_processor:
            try:
                self.audio_processor.cleanup()
                logging.info("AudioProcessor cleaned up")
            except Exception as e:
                logging.error(f"Error during AudioProcessor cleanup: {e}")
            self.audio_processor = None

        # Send LEAVE_ROOM message before disconnecting
        if self.tcp_sock and self.room_id:
            try:
                send_message(self.tcp_sock, PacketType.LEAVE_ROOM, {"room_id": self.room_id})
            except:
                pass

        # Wait for audio playback thread to exit
        if self._audio_playback_thread and self._audio_playback_thread.is_alive():
            self._audio_playback_thread.join(timeout=2.0)
            self._audio_playback_thread = None

        # Clear all per-sender audio buffers
        if self._sender_audio_buffers:
            with self._audio_lock:
                self._sender_audio_buffers.clear()

        # Close sockets
        if self.tcp_sock:
            try:
                self.tcp_sock.close()
            except:
                pass
            self.tcp_sock = None

        if self.udp_sock:
            try:
                self.udp_sock.close()
            except:
                pass
            self.udp_sock = None

        # Cleanup video processor
        try:
            self.processor.cleanup()
        except:
            pass

        logging.info("Cleanup complete")

    def set_camera_on(self, enabled: bool):
        """Toggle camera on/off and send state update to server."""
        if enabled:
            self.camera_on.set()
        else:
            self.camera_on.clear()
        self._send_state_update()

    def set_mic_muted(self, muted: bool):
        """Toggle mic mute/unmute and send state update to server."""
        if muted:
            self.mic_muted.set()
        else:
            self.mic_muted.clear()
        self._send_state_update()

    def _send_state_update(self):
        """Send state update (camera_on, mic_muted) to server via ROOM_STATE."""
        if not self.tcp_sock or self.room_id is None or self.client_id is None:
            return

        payload = {
            "room_id": self.room_id,
            "client_id": self.client_id,
            "camera_on": self.camera_on.is_set(),
            "mic_muted": self.mic_muted.is_set()
        }

        try:
            # Use ROOM_STATE type for state updates
            send_message(self.tcp_sock, PacketType.ROOM_STATE, payload)
            logging.debug("Sent state update: client_id=%d, camera_on=%s, mic_muted=%s",
                         self.client_id, payload["camera_on"], payload["mic_muted"])
        except Exception as e:
            logging.error(f"Failed to send state update: {e}")

    def _mix_audio_frames(self) -> Optional[bytes]:
        """
        Mix audio frames from all sender buffers into a single frame.
        Each sender contributes their LATEST frame (drop-oldest policy).
        Skips own audio to prevent echo.

        Returns:
            Mixed audio bytes (PCM 16-bit mono) or None if no audio to play.
        """
        with self._audio_lock:
            if not self._sender_audio_buffers:
                return None

            # Collect LATEST frame from each sender
            sender_frames = []
            senders_to_remove = []

            for sender_id, buffer in self._sender_audio_buffers.items():
                # Skip own audio to prevent echo
                if sender_id == self.client_id:
                    continue

                if buffer:
                    # Take the LATEST frame (rightmost), drop older ones
                    frame_bytes = buffer.pop()
                    frame = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.int32)
                    sender_frames.append(frame)
                else:
                    # Mark empty buffers for removal
                    senders_to_remove.append(sender_id)

            # Clean up empty sender buffers
            for sid in senders_to_remove:
                del self._sender_audio_buffers[sid]

            if not sender_frames:
                return None

            # Mix: average all frames to prevent clipping
            # When 6 people speak, averaging keeps volume reasonable
            mixed = np.zeros_like(sender_frames[0])
            for frame in sender_frames:
                mixed += frame

            # Normalize by number of senders (prevents clipping when 6 people speak)
            mixed = mixed // len(sender_frames)

            # Clip to int16 range (just in case)
            mixed = np.clip(mixed, -32768, 32767).astype(np.int16)

            return mixed.tobytes()

    def _audio_playback_loop(self):
        """Background thread to mix and play audio from per-sender buffers."""
        logging.info("Audio playback loop started")

        frame_interval = AUDIO_FRAME_MS / 1000.0  # Convert ms to seconds
        last_frame_time = time.time()

        while not self.stop_event.is_set():
            try:
                current_time = time.time()
                elapsed = current_time - last_frame_time

                # If it's time for next frame (20ms interval)
                if elapsed >= frame_interval:
                    # Mix audio from all senders
                    mixed_audio = self._mix_audio_frames()

                    if mixed_audio is not None and self.audio_processor:
                        self.audio_processor.play_frame(mixed_audio)

                    last_frame_time = current_time
                else:
                    # Sleep for remaining time to maintain 20ms interval
                    sleep_time = frame_interval - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    else:
                        # If we're significantly behind, just continue without sleeping
                        pass

            except Exception as e:
                logging.error(f"Audio playback loop error: {e}")
                time.sleep(0.1)

        logging.info("Audio playback loop exited")

    def _remove_sender_buffer(self, sender_id: int):
        """Remove audio buffer when a sender disconnects."""
        with self._audio_lock:
            if sender_id in self._sender_audio_buffers:
                del self._sender_audio_buffers[sender_id]
                logging.debug("Removed audio buffer for disconnected client %d", sender_id)

    def _tcp_listener_loop(self):
        """Background thread to listen for ROOM_STATE updates from server."""
        logging.info("TCP listener loop started")

        while not self.stop_event.is_set():
            try:
                # Listen for TCP messages (ROOM_STATE broadcasts from server)
                msg_type, payload = recv_message(self.tcp_sock)

                if msg_type is None:
                    # Connection closed or error
                    logging.warning("TCP connection closed")
                    break

                if msg_type == PacketType.ROOM_STATE:
                    # Update GUI with participant states
                    participants = payload.get("participants", [])
                    current_participant_ids = set()

                    if self.gui_window and participants:
                        for p in participants:
                            try:
                                client_id = p.get("client_id")
                                current_participant_ids.add(client_id)
                                camera_on = p.get("camera_on", True)
                                mic_muted = p.get("mic_muted", False)

                                # Get the CameraFrame for this client
                                slot_id = self.gui_window.client_slots.get(client_id)
                                if slot_id:
                                    frame = self.gui_window.video_frames.get(slot_id)
                                    if frame:
                                        frame.set_camera_on(camera_on)
                                        frame.set_mic_muted(mic_muted)
                            except Exception as e:
                                logging.error(f"Failed to update participant state: {e}")

                    # Clean up audio buffers for disconnected participants
                    with self._audio_lock:
                        disconnected = set(self._sender_audio_buffers.keys()) - current_participant_ids
                        for sid in disconnected:
                            if sid != self.client_id:  # Don't remove own buffer
                                del self._sender_audio_buffers[sid]
                                logging.debug("Removed audio buffer for disconnected client %d", sid)

                elif msg_type == PacketType.ERROR:
                    logging.warning(f"Server error: {payload.get('reason')}")

            except Exception as e:
                logging.error(f"TCP listener error: {e}")
                break

        logging.info("TCP listener loop exited")



if __name__ == "__main__":
    # Main entry point. Try to run GUI login flow, fallback to headless CLI when PyQt unavailable.

    # Parse CLI args for headless/fallback mode (keep for backward compatibility)
    parser = argparse.ArgumentParser(description="HexaCall Integrated Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP")
    parser.add_argument("--tcp", type=int, default=8000, help="Server TCP port")
    parser.add_argument("--udp", type=int, default=5000, help="Server UDP port")
    parser.add_argument("--room", type=int, default=1, help="Room ID (integer) to join")
    args = parser.parse_args()

    # Try to integrate with PyQt GUI. If PyQt is not available, fall back to headless mode.
    try:
        from PyQt6.QtWidgets import QApplication
        from Code.client.gui.login import LoginWindow
        from Code.client.gui.main_window import MainWindow

        app = QApplication(sys.argv)

        # Create login window
        login_window = LoginWindow()

        def on_login_connect(username, server_ip, port, room_id):
            """Handle login form submission."""
            # Close login window
            login_window.close()

            # Create HexaClient with validated parameters (UDP port = 5000 is server-managed)
            gui_client = HexaClient(server_ip, port, udp_port=5000)

            # Create main window and show
            window = MainWindow()
            window.set_client(gui_client)  # Wire client reference for toolbar
            window.show()

            # Run client in background thread with room_id from GUI and window instance
            client_thread = threading.Thread(
                target=gui_client.run,
                args=(room_id, window),
                daemon=True
            )
            client_thread.start()

            # Store client for cleanup
            app.client = gui_client

        # Connect login signal to handler
        login_window.connect_requested.connect(on_login_connect)

        # Show login window
        login_window.show()

        # Run Qt event loop. Ensure cleanup on exit.
        exit_code = app.exec()

        if hasattr(app, 'client'):
            app.client.cleanup()
        sys.exit(exit_code)

    except Exception as e:
        # PyQt not available or failed to start -> run in headless mode (CLI args used)
        logging.warning(
            f"PyQt GUI not available or failed to start ({e}). "
            "Running in headless mode using CLI args."
        )
        # Use args from CLI for headless run (connect -> join room)
        headless_client = HexaClient(args.host, args.tcp, args.udp)
        # Resume the CLI-assigned run() to join room (no GUI)
        headless_client.run(args.room)
