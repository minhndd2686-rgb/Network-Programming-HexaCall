"""
GUI Application Entry Point for HexaCall.

Usage:
    python main_app.py

This launches the interactive PyQt6 GUI with LoginWindow and MainWindow.
For command-line usage, use: python main_client.py --help
"""

import sys
import os

# Add project root to path
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
)

from Code.client.app_controller import AppController


if __name__ == "__main__":
    controller = AppController()
    sys.exit(controller.run())
