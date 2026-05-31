import cv2

print("Đang khởi tạo camera...")
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Lỗi: Không thể mở được camera! Hãy kiểm tra lại.")
    exit()

print("Camera đã mở thành công! Nhấn phím 'q' trên cửa sổ video để thoát.")

while True:
    ret, frame = cap.read()
    
    if not ret:
        print("Lỗi: Không thể đọc được khung hình!")
        break
        
    cv2.imshow('HexaCall - Vu Test Camera', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()