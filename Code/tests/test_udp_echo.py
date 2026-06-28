import socket
import sys
import os
import time

# Add path to import shared module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Code.shared.protocol import pack_udp_chunk, unpack_udp_chunk

def test_echo(host='127.0.0.1', port=5000):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)

    # Giả lập 1 video chunk
    client_id = 1
    room_id = 101
    frame_id = 1
    chunk_idx = 0
    total_chunks = 1
    payload = b"TEST_VIDEO_DATA_PHASE_2"

    packet = pack_udp_chunk(client_id, room_id, frame_id, chunk_idx, total_chunks, payload)

    print(f"Sending packet to {host}:{port}...")
    sock.sendto(packet, (host, port))

    try:
        data, addr = sock.recvfrom(65535)
        print(f"Received echo from {addr}")

        unpacked = unpack_udp_chunk(data)
        if unpacked:
            cid, rid, fid, cidx, total, pld = unpacked
            print(f"Decoded: Client={cid}, Room={rid}, Frame={fid}, Payload={pld.decode()}")
            if pld == payload:
                print("SUCCESS: Echo matches original!")
            else:
                print("ERROR: Payload mismatch.")
        else:
            print("ERROR: Could not unpack echo packet.")

    except socket.timeout:
        print("ERROR: Timeout - No response from server.")
    finally:
        sock.close()

if __name__ == "__main__":
    test_echo()
