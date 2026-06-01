import socket

HOST = "127.0.0.1"
PORT = 8000

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock.connect((HOST, PORT))

while True:
    msg = input("> ")

    sock.sendall(msg.encode())

    data = sock.recv(1024)

    print(data.decode())