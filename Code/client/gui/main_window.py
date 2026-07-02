"""
Main graphical user interface for the HexaCall client.

Responsibilities:
- Display video streams from multiple participants.
- Render OpenCV frames using QImage and QPixmap.
- Provide a thread-safe API for the networking module.
- Handle participant disconnections safely.
- Maintain a scalable grid layout for video feeds.
"""

import sys
import cv2
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QGridLayout,
    QLabel
)

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    pyqtSlot
)

from PyQt6.QtGui import (
    QImage,
    QPixmap
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
        self.setFixedSize(160, 160)  # Prevents widget from growing unpredictably
        self._set_waiting_state()

    def _set_waiting_state(self):
        """
        Display default waiting state.
        """

        self.setText(
            f"Camera {self.camera_id}\n(Waiting for connection...)"
        )

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
        """
        Convert an OpenCV frame into a QPixmap
        and display it inside the widget.
        """

        rgb_frame = cv2.cvtColor(
            cv_frame,
            cv2.COLOR_BGR2RGB
        )

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

        scaled_pixmap = self.current_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.setPixmap(scaled_pixmap)

    def reset(self):
        """
        Reset the video frame when a participant disconnects.
        Prevents frozen frames (ghost frames).
        """

        self.clear()

        self.current_pixmap = None

        self.setText(
            f"Camera {self.camera_id}\n(Disconnected)"
        )

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
        """
        Automatically rescale the displayed image
        when the widget size changes.
        """

        super().resizeEvent(event)

        if self.current_pixmap:

            self.setPixmap(
                self.current_pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )


class MainWindow(QMainWindow):
    """
    Main application window.

    Provides thread-safe communication between
    the networking layer and the GUI.
    """

    network_frame_signal = pyqtSignal(
        int,
        np.ndarray
    )

    disconnect_signal = pyqtSignal(
        int
    )

    def __init__(self, max_clients: int = 6):
        super().__init__()

        self.max_clients = max_clients
        self.video_frames = {}
        self.client_slots = {}
        self.slot_clients = {}

        self.setup_ui()

        self.network_frame_signal.connect(
            self.update_frame_slot
        )

        self.disconnect_signal.connect(
            self.handle_disconnect_slot
        )

    def setup_ui(self):
        """
        Create the main video grid layout.
        """

        self.setWindowTitle(
            "HexaCall - Video Conference"
        )

        self.resize(900, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        grid_layout = QGridLayout(
            central_widget
        )

        grid_layout.setSpacing(10)

        grid_layout.setContentsMargins(
            10,
            10,
            10,
            10
        )

        columns = 3

        for i in range(self.max_clients):

            client_id = i + 1

            frame_widget = CameraFrame(
                client_id
            )

            self.video_frames[
                client_id
            ] = frame_widget

            row = i // columns
            column = i % columns

            grid_layout.addWidget(
                frame_widget,
                row,
                column
            )

    def _find_free_slot(self):
        """Return first free GUI slot, or None if all slots are occupied."""

        for slot_id in range(1, self.max_clients + 1):
            if slot_id not in self.slot_clients:
                return slot_id

        return None

    def _get_or_assign_slot(
        self,
        client_id: int
    ):
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

    def update_network_frame(
        self,
        client_id: int,
        frame: np.ndarray
    ):
        """
        Public API used by the networking module
        to update video frames.
        """

        self.network_frame_signal.emit(
            client_id,
            frame
        )

    def notify_client_disconnected(
        self,
        client_id: int
    ):
        """
        Public API used by the networking module
        when a participant disconnects.
        """

        self.disconnect_signal.emit(
            client_id
        )

    @pyqtSlot(int, np.ndarray)
    def update_frame_slot(
        self,
        client_id: int,
        frame: np.ndarray
    ):
        """
        Thread-safe slot executed in the GUI thread.
        """

        slot_id = self._get_or_assign_slot(client_id)
        if slot_id is None:
            print(
                f"[WARNING] No free video slot for client ID: {client_id}"
            )
            return

        self.video_frames[
            slot_id
        ].set_image(frame)

    @pyqtSlot(int)
    def handle_disconnect_slot(
        self,
        client_id: int
    ):
        """
        Thread-safe slot executed when
        a participant disconnects.
        """

        slot_id = self.client_slots.pop(client_id, None)
        if slot_id is None:
            return

        self.slot_clients.pop(slot_id, None)
        self.video_frames[slot_id].reset()

        print(
            f"[INFO] Client {client_id} (slot {slot_id}) disconnected."
        )

    def get_camera_frame(
        self,
        client_id: int
    ):
        """
        Return a CameraFrame widget by client ID.
        """

        return self.video_frames.get(
            client_id
        )

    def reset_camera(
        self,
        client_id: int
    ):
        """
        Manually reset a camera frame.
        """

        if client_id in self.video_frames:

            self.video_frames[
                client_id
            ].reset()


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = MainWindow()

    window.show()

    sys.exit(app.exec())
