"""
Login GUI for HexaCall.

Provides a form for the user to enter username, server IP, port, and room ID
before connecting to the video conference.
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMainWindow, QMessageBox


class LoginWindow(QMainWindow):
    """
    Login window that collects connection parameters.

    Emits connect_requested signal with validated inputs (username, server_ip, port, room_id)
    for the main application to handle networking.
    """

    connect_requested = pyqtSignal(str, str, int, int, int)

    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.connect_button.clicked.connect(self.on_connect_clicked)

    def setup_ui(self):
        """Set up the login form UI with semantic widget names."""
        self.setObjectName("MainWindow")
        self.resize(469, 560    )

        self.centralwidget = QtWidgets.QWidget(parent=self)
        self.centralwidget.setObjectName("centralwidget")

        # Title label
        self.title_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.title_label.setGeometry(QtCore.QRect(130, 20, 231, 61))
        font = QtGui.QFont()
        font.setPointSize(25)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setObjectName("title_label")

        # Username label and input
        self.username_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.username_label.setGeometry(QtCore.QRect(20, 90, 111, 31))
        self.username_label.setObjectName("username_label")

        self.username_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.username_input.setGeometry(QtCore.QRect(20, 120, 431, 31))
        self.username_input.setObjectName("username_input")

        # Server IP label and input
        self.server_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.server_label.setGeometry(QtCore.QRect(20, 160, 111, 31))
        self.server_label.setObjectName("server_label")

        self.server_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.server_input.setGeometry(QtCore.QRect(20, 190, 431, 31))
        self.server_input.setObjectName("server_input")

        # Port TCP label and input
        self.port_tcp_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.port_tcp_label.setGeometry(QtCore.QRect(20, 230, 55, 16))
        self.port_tcp_label.setObjectName("port_tcp_label")

        self.port_tcp_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.port_tcp_input.setGeometry(QtCore.QRect(20, 250, 431, 31))
        self.port_tcp_input.setObjectName("port_tcp_input")


       # UDP Port label and input
        self.port_udp_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.port_udp_label.setGeometry(QtCore.QRect(20, 300, 111, 20))
        self.port_udp_label.setObjectName("port_udp_label")

        self.port_udp_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.port_udp_input.setGeometry(QtCore.QRect(20, 325, 431, 31))
        self.port_udp_input.setObjectName("port_udp_input")

        # Room ID label and input (NEW)
        self.room_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.room_label.setGeometry(QtCore.QRect(20, 370, 111, 20))
        self.room_label.setObjectName("room_label")

        self.room_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.room_input.setGeometry(QtCore.QRect(20, 395, 431, 31))
        self.room_input.setObjectName("room_input")
        self.room_input.setText("1")  # Default room ID

        # Connect button
        self.connect_button = QtWidgets.QPushButton(parent=self.centralwidget)
        self.connect_button.setGeometry(QtCore.QRect(185, 450, 100, 40))
        font = QtGui.QFont()
        font.setPointSize(10)
        self.connect_button.setFont(font)
        self.connect_button.setObjectName("connect_button")

        self.setCentralWidget(self.centralwidget)

        self.menubar = QtWidgets.QMenuBar(parent=self)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 469, 26))
        self.setMenuBar(self.menubar)

        self.statusbar = QtWidgets.QStatusBar(parent=self)
        self.setStatusBar(self.statusbar)

        self.retranslate_ui()
        QtCore.QMetaObject.connectSlotsByName(self)

    def retranslate_ui(self):
        """Set text labels and window title."""
        _translate = QtCore.QCoreApplication.translate

        self.setWindowTitle(_translate("MainWindow", "HexaCall Login"))
        self.title_label.setText(_translate("MainWindow", "HEXACALL"))
        self.username_label.setText(_translate("MainWindow", "Username:"))
        self.server_label.setText(_translate("MainWindow", "Server IP:"))
        self.port_tcp_label.setText(_translate("MainWindow", "TCP Port:"))
        self.port_udp_label.setText(_translate("MainWindow", "UDP Port:"))
        self.room_label.setText(_translate("MainWindow", "Room ID:"))
        self.connect_button.setText(_translate("MainWindow", "Connect"))

    def on_connect_clicked(self):
        """Validate inputs and emit connect_requested signal."""
        username = self.username_input.text().strip()
        server_ip = self.server_input.text().strip()
        port_tcp_text = self.port_tcp_input.text().strip()
        port_udp_text = self.port_udp_input.text().strip()
        room_text = self.room_input.text().strip()

        if not username:
            QMessageBox.warning(
                self,
                "Input Error",
                "Username cannot be empty."
            )
            return

        if not server_ip:
            QMessageBox.warning(
                self,
                "Input Error",
                "Server IP cannot be empty."
            )
            return

        tcp_port = self._validate_port(port_tcp_text)
        if tcp_port is None:
            return
        
        udp_port = self._validate_port(port_udp_text)
        if udp_port is None:
            return
        
        room_id = self._validate_room_id(room_text)
        if room_id is None:
            return

        # Emit signal with all four parameters
        self.connect_requested.emit(
            username, 
            server_ip, 
            tcp_port, 
            udp_port, 
            room_id)

    def _validate_port(self, port_text):
        """
        Validate port number in range 1-65535.

        Returns validated port as int, or None if invalid.
        """
        if not port_text.isdigit():
            QMessageBox.warning(
                self,
                "Input Error",
                "Port must be a number."
            )
            return None

        port = int(port_text)
        if port < 1 or port > 65535:
            QMessageBox.warning(
                self,
                "Input Error",
                "Port must be between 1 and 65535."
            )
            return None

        return port

    def _validate_room_id(self, room_text):
        """
        Validate room ID is a positive integer.

        Returns validated room_id as int, or None if invalid.
        """
        if not room_text.isdigit():
            QMessageBox.warning(
                self,
                "Input Error",
                "Room ID must be a positive integer."
            )
            return None

        room_id = int(room_text)
        if room_id < 1:
            QMessageBox.warning(
                self,
                "Input Error",
                "Room ID must be at least 1."
            )
            return None

        return room_id


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)

    login_window = LoginWindow()

    login_window.connect_requested.connect(
    lambda username, ip, tcp_port, udp_port, room: print(
        f"[CONNECT] Username={username}, "
        f"IP={ip}, TCP={tcp_port}, UDP={udp_port}, Room={room}"
    )
)

    login_window.show()

    sys.exit(app.exec())
