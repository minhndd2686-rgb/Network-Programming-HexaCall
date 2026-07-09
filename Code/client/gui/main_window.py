"""
Main graphical user interface for the HexaCall client.

Responsibilities:
- Display video streams from multiple participants.
- Render OpenCV frames using QImage and QPixmap.
- Provide a thread-safe API for the networking module.
- Handle participant disconnections safely.
- Maintain a scalable grid layout for video feeds.
- Toolbar controls for camera/mic toggle.
"""

import sys
import cv2
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QGridLayout,
    QLabel,
    QToolBar,
    QPushButton
)

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    pyqtSlot,
    QTimer
)

from PyQt6.QtGui import (
    QImage,
    QPixmap,
    QPainter,
    QBrush,
    QColor,
    QPen
)


class CameraFrame(QLabel):
    """
    Represents a single participant video frame.

    This widget is responsible only for displaying images
    and does not contain any networking logic.
    """

    def __init__(self, camera_id: int):
        super().__init__()

        self.camera_id = camera_id
        self.current_pixmap = None
        self.camera_on = True   # Track camera state
        self.mic_muted = False  # Track mic mute state
        self.setMinimumSize(160, 160)
        self.setFixedSize(160, 160)
        self._set_waiting_state()

    def _set_waiting_state(self):
        """Display default waiting state."""
        self.setText(f"Camera {self.camera_id}\n(Waiting for connection...)")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            background-color: #2c3e50;
            color: #ecf0f1;
            border: 2px solid #34495e;
            border-radius: 8px;
            font-size: 15px;
            font-weight: bold;
        """)

    def set_image(self, cv_frame: np.ndarray):
        """Convert an OpenCV frame into a QPixmap and display it."""
        if not self.camera_on:
            return

        rgb_frame = cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb_frame.shape
        bytes_per_line = channels * width

        q_image = QImage(
            rgb_frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888
        )

        self.current_pixmap = QPixmap.fromImage(q_image)
        self._refresh_pixmap()

    def _refresh_pixmap(self):
        """Apply scaled pixmap to label."""
        if self.current_pixmap is None:
            return
        scaled_pixmap = self.current_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)

    def set_camera_on(self, on: bool):
        """Update camera on/off state and refresh UI."""
        self.camera_on = on
        if on:
            # Camera turned on - restore waiting or video frame
            if self.current_pixmap is None:
                self._set_waiting_state()
            else:
                self._refresh_pixmap()
            self.update()
        else:
            # Camera turned off - show black background with message
            self.current_pixmap = None
            # Clear pixmap completely (must come BEFORE setText so text is visible)
            self.setPixmap(QPixmap())
            self.clear()
            self.setText("the client turned off the camera")
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setStyleSheet("""
                background-color: black;
                color: #ffffff;
                border: 2px solid #34495e;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            """)
            # Force layout/word-wrap for long message
            self.setWordWrap(True)
            self.update()

    def set_mic_muted(self, muted: bool):
        """Update mic mute state and refresh UI."""
        self.mic_muted = muted
        self.update()  # Trigger repaint to show/hide mic icon

    def reset(self):
        """Reset the video frame when a participant disconnects."""
        self.clear()
        self.current_pixmap = None
        self.setText(f"Camera {self.camera_id}\n(Disconnected)")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            background-color: black;
            color: #e74c3c;
            border: 2px solid #34495e;
            border-radius: 8px;
            font-size: 15px;
            font-weight: bold;
        """)

    def resizeEvent(self, event):
        """Automatically rescale the displayed image when the widget size changes."""
        super().resizeEvent(event)
        if self.current_pixmap:
            self._refresh_pixmap()

    def paintEvent(self, event):
        """Custom paint to draw mic icon overlay when needed."""
        super().paintEvent(event)
        if self.current_pixmap and self.mic_muted:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Red circle background (top-right corner)
            cx = self.width() - 18
            cy = 18
            painter.setBrush(QBrush(QColor(255, 0, 0, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(cx - 12, cy - 12, 24, 24)
            # Slash through the mic
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(cx - 8, cy - 8, cx + 8, cy + 8)
            painter.drawLine(cx + 8, cy - 8, cx - 8, cy + 8)


class MainWindow(QMainWindow):
    """
    Main application window.

    Provides thread-safe communication between
    the networking layer and the GUI.
    """

    network_frame_signal = pyqtSignal(int, np.ndarray)
    disconnect_signal = pyqtSignal(int)

    def __init__(self, max_clients: int = 6):
        super().__init__()

        self.max_clients = max_clients
        self.video_frames = {}
        self.client_slots = {}
        self.slot_clients = {}
        self.client = None  # HexaClient reference for toolbar controls

        # Debounce timers for camera/mic toggles
        self.camera_debounce_timer = QTimer()
        self.camera_debounce_timer.setSingleShot(True)
        self.camera_debounce_timer.timeout.connect(self._do_toggle_camera)

        self.mic_debounce_timer = QTimer()
        self.mic_debounce_timer.setSingleShot(True)
        self.mic_debounce_timer.timeout.connect(self._do_toggle_mic)

        self.setup_ui()

        self.network_frame_signal.connect(self.update_frame_slot)
        self.disconnect_signal.connect(self.handle_disconnect_slot)

    def setup_ui(self):
        """Create the main video grid layout and toolbar."""
        self.setWindowTitle("HexaCall - Video Conference")
        self.resize(900, 600)

        # Toolbar with camera/mic controls
        toolbar = QToolBar("Controls", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Camera toggle button
        self.camera_btn = QPushButton("📷 Camera On")
        self.camera_btn.setCheckable(True)
        self.camera_btn.setChecked(True)
        self.camera_btn.clicked.connect(self.toggle_camera)
        toolbar.addWidget(self.camera_btn)

        # Mic toggle button
        self.mic_btn = QPushButton("🎤 Unmuted")
        self.mic_btn.setCheckable(True)
        self.mic_btn.setChecked(False)
        self.mic_btn.clicked.connect(self.toggle_mic)
        toolbar.addWidget(self.mic_btn)

        # Central video grid
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        grid_layout = QGridLayout(central_widget)
        grid_layout.setSpacing(10)
        grid_layout.setContentsMargins(10, 10, 10, 10)

        columns = 3
        for i in range(self.max_clients):
            client_id = i + 1
            frame_widget = CameraFrame(client_id)
            self.video_frames[client_id] = frame_widget
            row = i // columns
            column = i % columns
            grid_layout.addWidget(frame_widget, row, column)

    def _find_free_slot(self):
        """Return first free GUI slot, or None if all slots are occupied."""
        for slot_id in range(1, self.max_clients + 1):
            if slot_id not in self.slot_clients:
                return slot_id
        return None

    def _get_or_assign_slot(self, client_id: int):
        """Return stable GUI slot for a network client ID."""
        slot_id = self.client_slots.get(client_id)
        if slot_id is not None:
            return slot_id

        slot_id = self._find_free_slot()
        if slot_id is None:
            return None

        self.client_slots[client_id] = slot_id
        self.slot_clients[slot_id] = client_id
        return slot_id

    def set_client(self, client):
        """Set the HexaClient reference for toolbar controls."""
        self.client = client

    def toggle_camera(self):
        """Request camera toggle with debounce."""
        if not self.client:
            return
        # Start/Restart debounce timer (200ms)
        self.camera_debounce_timer.start(200)

    def _do_toggle_camera(self):
        """Actually perform the camera toggle after debounce."""
        if not self.client:
            return
        new_state = self.camera_btn.isChecked()
        self.camera_btn.setText("📷 Camera On" if new_state else "📷 Camera Off")
        self.client.set_camera_on(new_state)

        # Immediately update local tile for instant feedback
        local_client_id = self.client.client_id
        if local_client_id is not None:
            slot_id = self.client_slots.get(local_client_id)
            if slot_id and slot_id in self.video_frames:
                self.video_frames[slot_id].set_camera_on(new_state)

    def toggle_mic(self):
        """Request mic toggle with debounce."""
        if not self.client:
            return
        # Start/Restart debounce timer (200ms)
        self.mic_debounce_timer.start(200)

    def _do_toggle_mic(self):
        """Actually perform the mic toggle after debounce."""
        if not self.client:
            return
        muted = self.mic_btn.isChecked()
        self.mic_btn.setText("🎤 Unmuted" if not muted else "🎤 Muted")
        self.client.set_mic_muted(muted)

    def update_network_frame(self, client_id: int, frame: np.ndarray):
        """Public API used by the networking module to update video frames."""
        self.network_frame_signal.emit(client_id, frame)

    def notify_client_disconnected(self, client_id: int):
        """Public API used by the networking module when a participant disconnects."""
        self.disconnect_signal.emit(client_id)

    @pyqtSlot(int, np.ndarray)
    def update_frame_slot(self, client_id: int, frame: np.ndarray):
        """Thread-safe slot executed in the GUI thread."""
        slot_id = self._get_or_assign_slot(client_id)
        if slot_id is None:
            print(f"[WARNING] No free video slot for client ID: {client_id}")
            return
        self.video_frames[slot_id].set_image(frame)

    @pyqtSlot(int)
    def handle_disconnect_slot(self, client_id: int):
        """Thread-safe slot executed when a participant disconnects."""
        slot_id = self.client_slots.pop(client_id, None)
        if slot_id is None:
            return
        self.slot_clients.pop(slot_id, None)
        self.video_frames[slot_id].reset()
        # Rebuild layout to fill the gap left by the disconnected client
        self.rebuild_participant_layout()
        print(f"[INFO] Client {client_id} (slot {slot_id}) disconnected.")

    def remove_participant_widget(self, client_id: int):
        """
        Remove a participant's widget when they disconnect.

        This method is thread-safe and can be called from any thread.
        It emits a signal to remove the widget in the GUI thread.
        """
        # Emit signal to remove widget in GUI thread-safe manner
        self.disconnect_signal.emit(client_id)

    def rebuild_participant_layout(self):
        """
        Rebuild the participant grid layout to fill gaps after disconnections.

        This method ensures that:
        - Empty slots are removed from the layout
        - Remaining participants are shifted to fill gaps
        - The layout remains contiguous with no empty placeholders
        """
        # Get the central widget's layout
        central_widget = self.centralWidget()
        if not central_widget:
            return

        grid_layout = central_widget.layout()
        if not grid_layout:
            return

        # Remove all widgets from the grid (iterate backwards to avoid index shift)
        for i in range(grid_layout.count() - 1, -1, -1):
            item = grid_layout.itemAt(i)
            if item and item.widget():
                grid_layout.removeWidget(item.widget())

        # Collect all currently connected clients
        active_clients = list(self.client_slots.keys())

        # Re-add widgets in the correct order (no gaps)
        columns = 3
        for idx, client_id in enumerate(sorted(active_clients)):
            slot_id = self.client_slots.get(client_id)
            if slot_id and slot_id in self.video_frames:
                row = idx // columns
                column = idx % columns
                grid_layout.addWidget(self.video_frames[slot_id], row, column)

        # Hide unused slots (those without a client assigned)
        for slot_id in range(1, self.max_clients + 1):
            if slot_id not in self.slot_clients:
                self.video_frames[slot_id].reset()
                self.video_frames[slot_id].hide()
            else:
                self.video_frames[slot_id].show()

    def get_camera_frame(self, client_id: int):
        """Return a CameraFrame widget by client ID."""
        return self.video_frames.get(client_id)

    def reset_camera(self, client_id: int):
        """Manually reset a camera frame."""
        if client_id in self.video_frames:
            self.video_frames[client_id].reset()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
