"""
Audio processing module for HexaCall.

Handles microphone capture and speaker playback using PyAudio.
Designed to work with raw PCM audio (16-bit mono 16 kHz, 20ms frames).
"""

import logging
import threading
import queue
from typing import Optional

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logging.warning("PyAudio not available. Audio features will be disabled.")

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from Code.shared.protocol import (
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_WIDTH,
    AUDIO_FRAME_SIZE,
    AUDIO_BYTES_PER_FRAME
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class AudioProcessor:
    """
    Manages audio capture and playback using PyAudio.

    Thread-safe singleton-style processor for microphone input and speaker output.
    Uses blocking I/O for capture and queue-based playback.
    """

    def __init__(self):
        """Initialize audio processor."""
        if not PYAUDIO_AVAILABLE:
            logging.error("Cannot initialize AudioProcessor: PyAudio not installed")
            self.available = False
            return

        self.available = True
        self.pa = pyaudio.PyAudio()

        # Capture (microphone)
        self.input_stream: Optional[pyaudio.Stream] = None
        self.capture_active = False

        # Playback (speaker)
        self.output_stream: Optional[pyaudio.Stream] = None
        self.playback_queue = queue.Queue(maxsize=50)  # ~1 second buffer
        self.playback_active = False
        self.playback_thread: Optional[threading.Thread] = None

        # Thread safety
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        logging.info("AudioProcessor initialized")

    def start_capture(self) -> bool:
        """
        Start microphone capture.

        Returns:
            bool: True if capture started successfully, False otherwise.
        """
        if not self.available:
            logging.warning("AudioProcessor not available - cannot start capture")
            return False

        with self._lock:
            if self.capture_active:
                logging.warning("Capture already active")
                return True

            try:
                self.input_stream = self.pa.open(
                    format=pyaudio.paInt16,
                    channels=AUDIO_CHANNELS,
                    rate=AUDIO_SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=AUDIO_FRAME_SIZE,
                    stream_callback=None  # Blocking mode
                )
                self.capture_active = True
                logging.info("Microphone capture started")
                return True
            except Exception as e:
                logging.error(f"Failed to start capture: {e}")
                return False

    def stop_capture(self):
        """Stop microphone capture."""
        with self._lock:
            if self.input_stream and self.capture_active:
                try:
                    self.input_stream.stop_stream()
                    self.input_stream.close()
                except Exception as e:
                    logging.error(f"Error stopping capture: {e}")
                finally:
                    self.input_stream = None
                    self.capture_active = False
                    logging.info("Microphone capture stopped")

    def read_frame(self) -> Optional[bytes]:
        """
        Read one audio frame from microphone (blocking).

        Returns:
            bytes: PCM audio data (640 bytes for 20ms at 16kHz mono 16-bit), or None on error.
        """
        if not self.capture_active or not self.input_stream:
            return None

        try:
            # Read exactly one frame (320 samples = 640 bytes)
            data = self.input_stream.read(AUDIO_FRAME_SIZE, exception_on_overflow=False)
            return data
        except Exception as e:
            logging.error(f"Error reading audio frame: {e}")
            return None

    def start_playback(self) -> bool:
        """
        Start speaker playback.

        Returns:
            bool: True if playback started successfully, False otherwise.
        """
        if not self.available:
            logging.warning("AudioProcessor not available - cannot start playback")
            return False

        with self._lock:
            if self.playback_active:
                logging.warning("Playback already active")
                return True

            try:
                self.output_stream = self.pa.open(
                    format=pyaudio.paInt16,
                    channels=AUDIO_CHANNELS,
                    rate=AUDIO_SAMPLE_RATE,
                    output=True,
                    frames_per_buffer=AUDIO_FRAME_SIZE
                )

                # Start playback thread
                self._stop_event.clear()
                self.playback_thread = threading.Thread(
                    target=self._playback_loop,
                    name="AudioPlayback",
                    daemon=True
                )
                self.playback_thread.start()

                self.playback_active = True
                logging.info("Speaker playback started")
                return True
            except Exception as e:
                logging.error(f"Failed to start playback: {e}")
                return False

    def stop_playback(self):
        """Stop speaker playback."""
        with self._lock:
            if not self.playback_active:
                return

            self.playback_active = False
            self._stop_event.set()

        # Wait for playback thread to exit
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=2.0)

        with self._lock:
            if self.output_stream:
                try:
                    self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception as e:
                    logging.error(f"Error stopping playback: {e}")
                finally:
                    self.output_stream = None
                    # Clear queue
                    while not self.playback_queue.empty():
                        try:
                            self.playback_queue.get_nowait()
                        except queue.Empty:
                            break
                    logging.info("Speaker playback stopped")

    def _playback_loop(self):
        """Background thread that plays audio from queue."""
        logging.info("Playback loop started")

        while not self._stop_event.is_set():
            try:
                # Wait for audio data with timeout
                audio_data = self.playback_queue.get(timeout=0.1)

                if self.output_stream and self.playback_active:
                    try:
                        self.output_stream.write(audio_data)
                    except Exception as e:
                        logging.error(f"Error writing to output stream: {e}")
                        break
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Playback loop error: {e}")
                break

        logging.info("Playback loop exited")

    def play_frame(self, audio_data: bytes) -> bool:
        """
        Queue audio frame for playback (non-blocking).

        Args:
            audio_data: PCM audio bytes to play.

        Returns:
            bool: True if queued successfully, False if queue full or error.
        """
        if not self.playback_active:
            return False

        try:
            self.playback_queue.put_nowait(audio_data)
            return True
        except queue.Full:
            logging.debug("Playback queue full, dropping frame")
            return False
        except Exception as e:
            logging.error(f"Error queueing audio frame: {e}")
            return False

    def cleanup(self):
        """Clean up all audio resources."""
        logging.info("Cleaning up AudioProcessor")
        self.stop_capture()
        self.stop_playback()

        if self.available and self.pa:
            try:
                self.pa.terminate()
            except Exception as e:
                logging.error(f"Error terminating PyAudio: {e}")

        logging.info("AudioProcessor cleanup complete")


# Quick test
if __name__ == "__main__":
    if not PYAUDIO_AVAILABLE:
        print("PyAudio not available. Install with: pip install pyaudio")
        sys.exit(1)

    print("Testing AudioProcessor (5 second loopback test)")
    print("Speak into your microphone - you should hear yourself with slight delay")

    processor = AudioProcessor()

    # Start capture and playback
    if not processor.start_capture():
        print("Failed to start capture")
        sys.exit(1)

    if not processor.start_playback():
        print("Failed to start playback")
        processor.cleanup()
        sys.exit(1)

    # Loopback for 5 seconds
    import time
    start_time = time.time()
    frames_processed = 0

    try:
        while time.time() - start_time < 5.0:
            frame = processor.read_frame()
            if frame:
                processor.play_frame(frame)
                frames_processed += 1
            time.sleep(0.01)  # Small sleep to avoid busy loop
    except KeyboardInterrupt:
        print("\nInterrupted by user")

    print(f"\nProcessed {frames_processed} frames")
    processor.cleanup()
    print("Test complete")
