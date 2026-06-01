import cv2

print("Đang khởi tạo camera...")
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Lỗi: Không thể mở được camera!")
    exit()

print("Camera đã mở! Nhấn phím 'q' trên cửa sổ video để thoát.")

while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    # Nén khung hình sang định dạng JPEG với chất lượng 80%
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
    result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
    
    # Chuyển đổi khung hình đã nén thành chuỗi byte (sẵn sàng truyền qua mạng)
    byte_data = encoded_frame.tobytes()
    
    # In dung lượng của gói dữ liệu ra màn hình Terminal
    print(f"Dung lượng hiện tại: {len(byte_data)} bytes        ", end='\r')
    
    # Hiển thị video
    cv2.imshow('HexaCall - Vu Test Camera', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()