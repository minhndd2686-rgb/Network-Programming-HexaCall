"""
Module providing the main graphical user interface for the HexaCall client.
Implements Thread-Safe UI updates for Network Programming standards.
"""

import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap

class CameraFrame(QLabel):
    """
    A custom QLabel class representing an individual camera feed frame.
    Ensures OOP encapsulation by managing its own UI state.
    """
    def __init__(self, camera_id: int):
        super().__init__()
        self.camera_id = camera_id
        
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
        """
        Updates the camera frame. Isolated from network logic.
        """
        cv_rgb_image = cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB)
        
        height, width, channel = cv_rgb_image.shape
        bytes_per_line = 3 * width
        
        q_image = QImage(cv_rgb_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        
        pixmap = QPixmap.fromImage(q_image)
        scaled_pixmap = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        self.setPixmap(scaled_pixmap)


class MainWindow(QMainWindow):
    """
    Main Window manager. Exposes a thread-safe Signal for the Network module.
    """
    network_frame_signal = pyqtSignal(int, np.ndarray)

    def __init__(self, max_clients: int = 6):
        super().__init__()
        self.max_clients = max_clients
        self.video_frames = {} 
        
        self.setup_ui()
        self.network_frame_signal.connect(self.update_frame_slot)

    def setup_ui(self):
        """
        Initializes the grid layout consistently.
        """
        self.setWindowTitle("HexaCall - Client GUI")
        self.resize(900, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        grid_layout = QGridLayout(central_widget)
        grid_layout.setSpacing(10)
        grid_layout.setContentsMargins(10, 10, 10, 10)

        cols = 3 

        for i in range(self.max_clients):
            cam_id = i + 1
            frame = CameraFrame(cam_id)
            self.video_frames[cam_id] = frame 
            
            row = i // cols
            col = i % cols
            grid_layout.addWidget(frame, row, col)

    @pyqtSlot(int, np.ndarray)
    def update_frame_slot(self, client_id: int, cv_frame: np.ndarray):
        """
        Thread-safe slot. Only triggered via network_frame_signal.emit().
        """
        if client_id in self.video_frames:
            self.video_frames[client_id].set_image(cv_frame)
        else:
            print(f"[WARNING] Received data from unknown client_id: {client_id}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())    