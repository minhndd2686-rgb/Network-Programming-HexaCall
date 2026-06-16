from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMainWindow, QMessageBox


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(469, 446)

        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        self.label = QtWidgets.QLabel(parent=self.centralwidget)
        self.label.setGeometry(QtCore.QRect(130, 20, 231, 61))
        font = QtGui.QFont()
        font.setPointSize(25)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setObjectName("label")

        self.label_2 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_2.setGeometry(QtCore.QRect(20, 90, 111, 31))
        self.label_2.setObjectName("label_2")

        self.lineEdit = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.lineEdit.setGeometry(QtCore.QRect(20, 120, 431, 31))
        self.lineEdit.setObjectName("lineEdit")

        self.label_3 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_3.setGeometry(QtCore.QRect(20, 160, 111, 31))
        self.label_3.setObjectName("label_3")

        self.lineEdit_2 = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.lineEdit_2.setGeometry(QtCore.QRect(20, 190, 431, 31))
        self.lineEdit_2.setObjectName("lineEdit_2")

        self.label_4 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_4.setGeometry(QtCore.QRect(20, 240, 55, 16))
        self.label_4.setObjectName("label_4")

        self.lineEdit_3 = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.lineEdit_3.setGeometry(QtCore.QRect(20, 260, 431, 31))
        self.lineEdit_3.setObjectName("lineEdit_3")

        self.pushButton = QtWidgets.QPushButton(parent=self.centralwidget)
        self.pushButton.setGeometry(QtCore.QRect(190, 330, 93, 41))
        font = QtGui.QFont()
        font.setPointSize(10)
        self.pushButton.setFont(font)
        self.pushButton.setObjectName("pushButton")

        MainWindow.setCentralWidget(self.centralwidget)

        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 469, 26))
        MainWindow.setMenuBar(self.menubar)

        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate

        MainWindow.setWindowTitle(_translate("MainWindow", "HexaCall Login"))
        self.label.setText(_translate("MainWindow", "HEXACALL"))
        self.label_2.setText(_translate("MainWindow", "Username:"))
        self.label_3.setText(_translate("MainWindow", "Server IP:"))
        self.label_4.setText(_translate("MainWindow", "Port:"))
        self.pushButton.setText(_translate("MainWindow", "Connect"))


class LoginWindow(QMainWindow):

    # Signal emitted when the user requests a server connection
    connect_requested = pyqtSignal(str, str, int)

    def __init__(self):
        super().__init__()

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.pushButton.clicked.connect(
            self.on_connect_clicked
        )

    def on_connect_clicked(self):

        username = self.ui.lineEdit.text().strip()
        server_ip = self.ui.lineEdit_2.text().strip()
        port_text = self.ui.lineEdit_3.text().strip()

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

        if not port_text.isdigit():
            QMessageBox.warning(
                self,
                "Input Error",
                "Port must be a number."
            )
            return

        port = int(port_text)

        # Send data for module networking
        self.connect_requested.emit(
            username,
            server_ip,
            port
        )


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)

    login_window = LoginWindow()

    login_window.connect_requested.connect(
        lambda username, ip, port:
        print(
            f"[CONNECT] Username={username}, IP={ip}, Port={port}"
        )
    )

    login_window.show()

    sys.exit(app.exec())
