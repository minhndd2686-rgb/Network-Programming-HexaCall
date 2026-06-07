import cv2
import numpy as np

class FrameProcessor:
    def __init__(self, camera_index=0, jpeg_quality=80):
        # Initialize camera and compression parameters
        self.camera_index = camera_index
        self.jpeg_quality = jpeg_quality
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print(f"Warning: Cannot open camera {self.camera_index}")

    def capture_and_compress(self):
        """Reads a frame from the camera and compresses it to JPEG bytes."""
        if not self.cap.isOpened():
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None

        # Compress frame to JPEG
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
        
        if result:
            return encoded_frame.tobytes()
        return None

    def decompress_to_frame(self, byte_data):
        """Decompresses JPEG bytes back into an OpenCV image frame."""
        if not byte_data:
            return None
            
        # Decode bytes back to frame
        nparr = np.frombuffer(byte_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return frame

    def cleanup(self):
        """Releases the camera resource."""
        if self.cap.isOpened():
            self.cap.release()

# --- Quick Test ---
if __name__ == "__main__":
    # Test to ensure the OOP class works correctly
    processor = FrameProcessor()
    
    print("Testing FrameProcessor... Press 'q' to quit.")
    while True:
        # 1. Test Capture & Compress
        compressed_bytes = processor.capture_and_compress()
        
        if compressed_bytes:
            # 2. Test Decompress
            recovered_frame = processor.decompress_to_frame(compressed_bytes)
            
            if recovered_frame is not None:
                cv2.imshow("G3 Media Test - OOP", recovered_frame)
                
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    processor.cleanup()
    cv2.destroyAllWindows()