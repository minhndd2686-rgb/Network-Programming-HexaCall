"""
Main graphical user interface for the HexaCall client.

Responsibilities:
- Display video streams from multiple participants.
- Render OpenCV frames using QImage and QPixmap.
- Provide a thread-safe API for the networking module.
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
        Reset the widget to its default state.
        """

        self.clear()

        self.setText(
            f"Camera {self.camera_id}\n(Waiting for connection...)"
        )

        self.current_pixmap = None

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

    Provides a thread-safe interface for the networking module
    through Qt Signals and Slots.
    """

    network_frame_signal = pyqtSignal(
        int,
        np.ndarray
    )

    def __init__(self, max_clients: int = 6):
        super().__init__()

        self.max_clients = max_clients
        self.video_frames = {}

        self.setup_ui()

        self.network_frame_signal.connect(
            self.update_frame_slot
        )

    def setup_ui(self):
        """
        Create the main video grid layout.
        """

        self.setWindowTitle("HexaCall - Video Conference")

        self.resize(900, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        grid_layout = QGridLayout(central_widget)

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

            frame_widget = CameraFrame(client_id)

            self.video_frames[client_id] = frame_widget

            row = i // columns
            column = i % columns

            grid_layout.addWidget(
                frame_widget,
                row,
                column
            )

    def update_network_frame(
        self,
        client_id: int,
        frame: np.ndarray
    ):
        """
        Public API for the networking module.

        Networking threads should call this method
        instead of directly manipulating GUI widgets.
        """

        self.network_frame_signal.emit(
            client_id,
            frame
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

        if client_id in self.video_frames:

            self.video_frames[client_id].set_image(
                frame
            )

        else:
            print(
                f"[WARNING] Unknown client ID: {client_id}"
            )

    def get_camera_frame(
        self,
        client_id: int
    ):
        """
        Return a CameraFrame widget by client ID.
        """

        return self.video_frames.get(client_id)

    def reset_camera(
        self,
        client_id: int
    ):
        """
        Reset a specific camera frame.
        """

        if client_id in self.video_frames:

            self.video_frames[client_id].reset()


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = MainWindow()

    window.show()

    sys.exit(app.exec())
