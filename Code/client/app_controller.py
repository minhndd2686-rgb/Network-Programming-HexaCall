"""
Application Controller for HexaCall GUI Integration.

Responsibilities:
1. Instantiate and manage LoginWindow and MainWindow
2. Instantiate and manage HexaClient network stack
3. Route signals between GUI and networking layers
4. Manage application lifecycle (login → connection → disconnect)
5. Handle errors and state transitions safely

This controller maintains loose coupling between GUI and networking
by using callbacks and Qt signals, allowing independent testing.
"""

import sys
import threading
import logging

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

# Import client modules
from gui.login import LoginWindow
from gui.main_window import MainWindow
from main_client import HexaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class AppController:
    """
    Central controller that orchestrates GUI ↔ Network integration.
    
    State Flow:
    1. __init__(): Create windows (not shown)
    2. run(): Show LoginWindow, enter Qt event loop
    3. on_login_requested(): User submits login form
    4. on_connection_successful(): Hide LoginWindow, show MainWindow
    5. on_frame_received(): Relay network frames to MainWindow
    6. cleanup(): Close connections, cleanup threads
    """

    def __init__(self):
        """Initialize controller with GUI components (not displayed yet)."""
        self.app = None
        self.login_window = None
        self.main_window = None
        self.hex_client = None
        self.client_thread = None
        self.app_state = "login"  # 'login', 'connecting', 'connected', 'error'

    def run(self):
        """
        Main entry point. Creates Qt application and starts GUI.
        
        Returns:
            int: Exit code from Qt event loop
        """
        # Create Qt application (must be done before any Qt widgets)
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        # Instantiate GUI components
        self.login_window = LoginWindow()
        self.main_window = MainWindow()

        # Connect LoginWindow signals to controller slots
        self.login_window.connect_requested.connect(
            self.on_login_requested
        )

        # Connect MainWindow cleanup (optional - for graceful shutdown)
        self.main_window.closeEvent = self.on_main_window_closed

        # Show login window and start event loop
        logger.info("Launching HexaCall GUI")
        self.login_window.show()

        return self.app.exec()

    def on_login_requested(self, username: str, server_ip: str, port: int):
        """
        Slot called when user submits login form.
        
        Flow:
        1. Validate input
        2. Create HexaClient
        3. Attempt TCP connection
        4. Attempt to join room
        5. On success: hide login, show main window
        6. Start HexaClient in background thread
        
        Args:
            username: Username from login form
            server_ip: Server IP from login form
            port: Server TCP port from login form
        """
        logger.info(f"Login requested: {username}@{server_ip}:{port}")

        # Update state
        self.app_state = "connecting"

        try:
            # Create HexaClient with user-provided connection info
            self.hex_client = HexaClient(
                host=server_ip,
                tcp_port=port,
                udp_port=port + 1  # Convention: UDP port = TCP port + 1
            )

            # Step 1: Attempt TCP connection (gets client_id)
            logger.info("Attempting TCP connection...")
            if not self.hex_client.connect():
                raise ConnectionError("TCP connection failed")

            # Step 2: Join room (use username as room identifier)
            room_id = "room1"  # Could also use username or "main_room"
            logger.info(f"Joining room: {room_id}")
            if not self.hex_client.join_room(room_id):
                raise ConnectionError("Failed to join room")

            # Step 3: Setup frame callbacks BEFORE starting receiver thread
            # These callbacks route network frames back to MainWindow
            self.hex_client.frame_callback = self.on_frame_received
            self.hex_client.error_callback = self.on_client_error
            self.hex_client.disconnect_callback = self.on_client_disconnected

            # Step 4: Hide login window, show main window
            self.login_window.hide()
            self.main_window.show()

            # Step 5: Start HexaClient in background thread
            # HexaClient.run() blocks on UDP receive loop, so we run it in a daemon thread
            self.client_thread = threading.Thread(
                target=self.hex_client.run,
                args=(room_id,),  # room_id parameter
                daemon=True,  # Daemon thread: will be killed on app exit
                name="HexaClient-Receiver"
            )
            self.client_thread.start()
            logger.info("HexaClient receiver thread started")

            self.app_state = "connected"

        except Exception as e:
            logger.error(f"Login failed: {e}")
            self.app_state = "error"
            QMessageBox.critical(
                self.login_window,
                "Connection Failed",
                f"Failed to connect: {str(e)}"
            )

    def on_frame_received(self, sender_id: int, frame):
        """
        Callback invoked by HexaClient when a complete frame is received.
        
        Routes the frame from the network layer (running in background thread)
        to the GUI layer safely using Qt signals.
        
        Args:
            sender_id: ID of the client who sent this frame
            frame: OpenCV frame (numpy.ndarray)
        """
        if self.main_window and self.app_state == "connected":
            # Use Qt signal to route frame to GUI thread safely
            self.main_window.update_network_frame(sender_id, frame)

    def on_client_disconnected(self, client_id: int):
        """
        Callback invoked by HexaClient when a remote client disconnects.
        
        Routes the disconnection event to MainWindow.
        
        Args:
            client_id: ID of the client who disconnected
        """
        if self.main_window and self.app_state == "connected":
            self.main_window.notify_client_disconnected(client_id)

    def on_client_error(self, error_msg: str):
        """
        Callback invoked by HexaClient on network errors.
        
        Args:
            error_msg: Human-readable error message
        """
        logger.error(f"Network error: {error_msg}")
        if self.app_state == "connected":
            QMessageBox.warning(
                self.main_window,
                "Network Error",
                error_msg
            )

    def on_main_window_closed(self, event):
        """
        Cleanup when main window is closed by user.
        
        Ensures HexaClient is properly shut down.
        """
        logger.info("Main window closed, cleaning up...")
        self.cleanup()
        event.accept()

    def cleanup(self):
        """
        Gracefully shutdown all components.
        
        - Stops HexaClient and its threads
        - Closes sockets
        - Allows background thread to exit
        """
        if self.hex_client:
            logger.info("Shutting down HexaClient...")
            self.hex_client.cleanup()

        # Note: daemon threads will be killed automatically on app exit


def main():
    """Entry point for GUI application."""
    controller = AppController()
    exit_code = controller.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
