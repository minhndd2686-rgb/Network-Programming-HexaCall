"""
Login GUI for HexaCall Video Conferencing

Provides a form for the user to enter connection parameters:
- Username
- Server IP address
- TCP port (signaling)
- UDP port (video/audio streaming)
- Room ID to join
"""

import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class LoginWindow(QMainWindow):
    """Login window for HexaCall connection setup."""

    # Signal emitted when connect button is clicked
    connect_requested = pyqtSignal(str, str, int, int, int)  # username, ip, tcp_port, udp_port, room_id

    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        """Setup the login window UI."""
        self.setWindowTitle("HexaCall - Login")
        self.setFixedSize(500, 450)

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        # Title
        title_label = QLabel("HexaCall")
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center alignment
        layout.addWidget(title_label)

        # Username
        username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your display name")
        layout.addWidget(username_label)
        layout.addWidget(self.username_input)

        # Server IP
        server_label = QLabel("Server IP:")
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("127.0.0.1")
        self.server_input.setText("127.0.0.1")
        layout.addWidget(server_label)
        layout.addWidget(self.server_input)

        # Port inputs in horizontal layout
        ports_layout = QHBoxLayout()

        # TCP port
        tcp_label = QLabel("TCP Port:")
        self.tcp_input = QLineEdit()
        self.tcp_input.setPlaceholderText("8000")
        self.tcp_input.setText("8000")
        ports_layout.addWidget(tcp_label)
        ports_layout.addWidget(self.tcp_input)

        # UDP port
        udp_label = QLabel("UDP Port:")
        self.udp_input = QLineEdit()
        self.udp_input.setPlaceholderText("5000")
        self.udp_input.setText("5000")
        ports_layout.addWidget(udp_label)
        ports_layout.addWidget(self.udp_input)

        layout.addLayout(ports_layout)

        # Room ID
        room_label = QLabel("Room ID:")
        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("1")
        self.room_input.setText("1")
        layout.addWidget(room_label)
        layout.addWidget(self.room_input)

        # Spacer
        layout.addStretch()

        # Connect button
        self.connect_button = QPushButton("Connect")
        self.connect_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        layout.addWidget(self.connect_button)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.status_label)

    def setup_connections(self):
        """Connect UI signals to slots."""
        self.connect_button.clicked.connect(self.handle_connect)

    def handle_connect(self):
        """Validate inputs and emit connect signal."""
        # Get values
        username = self.username_input.text().strip()
        server_ip = self.server_input.text().strip()
        tcp_port_text = self.tcp_input.text().strip()
        udp_port_text = self.udp_input.text().strip()
        room_text = self.room_input.text().strip()

        # Validate username
        if not username:
            QMessageBox.warning(self, "Validation Error", "Username cannot be empty.")
            return

        # Validate server IP
        if not server_ip:
            QMessageBox.warning(self, "Validation Error", "Server IP cannot be empty.")
            return

        # Validate TCP port
        try:
            tcp_port = int(tcp_port_text)
            if not (1 <= tcp_port <= 65535):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation Error", "TCP port must be a valid port number (1-65535).")
            return

        # Validate UDP port
        try:
            udp_port = int(udp_port_text)
            if not (1 <= udp_port <= 65535):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation Error", "UDP port must be a valid port number (1-65535).")
            return

        # Validate room ID
        try:
            room_id = int(room_text)
            if room_id < 1:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation Error", "Room ID must be a positive integer.")
            return

        # Update status
        self.status_label.setText("Connecting...")
        self.connect_button.setEnabled(False)

        # Emit signal
        self.connect_requested.emit(username, server_ip, tcp_port, udp_port, room_id)

    def reset_status(self):
        """Reset the status label and re-enable connect button."""
        self.status_label.setText("")
        self.connect_button.setEnabled(True)


if __name__ == "__main__":
    """Test the login window standalone."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Create and show login window
    login_window = LoginWindow()
    login_window.show()

    # Connect signal to print debug info
    def debug_connect(username, ip, tcp_port, udp_port, room_id):
        print(f"[DEBUG] Connect requested:")
        print(f"  Username: {username}")
        print(f"  Server IP: {ip}")
        print(f"  TCP port: {tcp_port}")
        print(f"  UDP port: {udp_port}")
        print(f"  Room ID: {room_id}")

    login_window.connect_requested.connect(debug_connect)

    sys.exit(app.exec())
