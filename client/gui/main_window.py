import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout, QLabel
from PyQt6.QtCore import Qt

class CameraFrame(QLabel):
    def __init__(self, camera_id):
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

    def set_image(self, image_data):
        pass

class MainWindow(QMainWindow):
    def __init__(self, max_clients=6):
        super().__init__()
        self.max_clients = max_clients
        self.video_frames = {} 
        self.setup_ui()

    def setup_ui(self):
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

    def update_frame_from_network(self, client_id, frame_data):
        if client_id in self.video_frames:
            self.video_frames[client_id].set_image(frame_data)
        else:
            print(f"[WARNING] Received data from unknown client_id: {client_id}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())