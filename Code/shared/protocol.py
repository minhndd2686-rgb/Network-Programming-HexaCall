import struct
import json
import socket
import time
from enum import IntEnum
from typing import Dict, Any, Tuple, Optional, List

# ==== CONSTANTS & CONFIG ====
TCP_HEADER_FORMAT = "!BI"  # Type (1 byte), Length (4 bytes)
TCP_HEADER_SIZE = struct.calcsize(TCP_HEADER_FORMAT)

# UDP Header (20 bytes):
# Magic(4s), Version(B), Type(B), ClientID(H), RoomID(H), FrameID(I), ChunkIdx(H), TotalChunks(H), PayloadLen(H)
UDP_MAGIC = b'HXVC'
UDP_VERSION = 1
UDP_HEADER_FORMAT = "!4sBBHHIHHH"
UDP_HEADER_SIZE = struct.calcsize(UDP_HEADER_FORMAT)

MTU = 1500
# UDP Payload max = MTU - IP Header (20) - UDP Header (8) - Hexa Protocol Header (20)
UDP_MAX_PAYLOAD = MTU - 20 - 8 - UDP_HEADER_SIZE

class PacketType(IntEnum):
    """Protocol message types for HexaCall"""
    LOGIN = 1
    JOIN_ROOM = 2
    LEAVE_ROOM = 3
    ROOM_STATE = 4
    ERROR = 5
    CHAT = 6
    VIDEO_DATA = 7  # UDP Video chunk

# ==== TCP HELPERS (Signaling) ====

def pack_message(msg_type: int, payload: Dict[str, Any]) -> bytes:
    """
    Packs a message into [Header(5b)][Payload(JSON)]
    Header: !BI (Type 1b, Length 4b)
    """
    payload_data = json.dumps(payload).encode('utf-8')
    payload_len = len(payload_data)
    header = struct.pack(TCP_HEADER_FORMAT, msg_type, payload_len)
    return header + payload_data

def recv_all(sock: socket.socket, n: int, timeout: float = 5.0) -> Optional[bytes]:
    """
    Helper to receive exactly n bytes or return None if EOF/timeout.
    
    Args:
        sock: Socket to receive from
        n: Number of bytes to receive
        timeout: Socket timeout in seconds (default 5.0)
    
    Returns:
        bytes if successful, None if EOF or timeout
    """
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except (socket.error, ConnectionResetError):
            return None
        except socket.timeout:
            return None
    return bytes(data)

def recv_message(sock: socket.socket, timeout: float = 5.0) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """
    Receives a complete TCP message using framing.
    
    Args:
        sock: Socket to receive from
        timeout: Socket timeout in seconds (default 5.0)
    
    Returns:
        (msg_type, payload_dict) on success
        (None, None) on error/disconnect/timeout
    """
    header_data = recv_all(sock, TCP_HEADER_SIZE, timeout)
    if not header_data:
        return None, None

    msg_type, payload_len = struct.unpack(TCP_HEADER_FORMAT, header_data)

    if payload_len > 0:
        payload_data = recv_all(sock, payload_len, timeout)
        if not payload_data:
            return None, None
        try:
            payload = json.loads(payload_data.decode('utf-8'))
            return msg_type, payload
        except json.JSONDecodeError:
            return None, None

    return msg_type, {}

def send_message(sock: socket.socket, msg_type: int, payload: Dict[str, Any]):
    """Convenience helper to pack and send a TCP message"""
    sock.sendall(pack_message(msg_type, payload))

# ==== UDP HELPERS (Video Streaming) ====

def pack_udp_chunk(client_id: int, room_id: int, frame_id: int, chunk_idx: int, total_chunks: int, data: bytes) -> bytes:
    """Packs a video chunk with its 20-byte binary header"""
    payload_len = len(data)
    header = struct.pack(
        UDP_HEADER_FORMAT,
        UDP_MAGIC,
        UDP_VERSION,
        int(PacketType.VIDEO_DATA),
        client_id,
        room_id,
        frame_id,
        chunk_idx,
        total_chunks,
        payload_len
    )
    return header + data

def unpack_udp_chunk(data: bytes) -> Optional[Tuple[int, int, int, int, int, bytes]]:
    """
    Unpacks a video chunk.
    Returns (client_id, room_id, frame_id, chunk_idx, total_chunks, payload) or None if invalid.
    """
    if len(data) < UDP_HEADER_SIZE:
        return None

    header = data[:UDP_HEADER_SIZE]
    payload = data[UDP_HEADER_SIZE:]

    magic, version, p_type, client_id, room_id, frame_id, chunk_idx, total_chunks, payload_len = struct.unpack(UDP_HEADER_FORMAT, header)

    # Validation
    if magic != UDP_MAGIC or version != UDP_VERSION:
        return None
    if len(payload) != payload_len:
        return None

    return client_id, room_id, frame_id, chunk_idx, total_chunks, payload

def chunk_frame(client_id: int, room_id: int, frame_id: int, frame_data: bytes) -> List[bytes]:
    """Splits a large frame into multiple UDP-safe chunks"""
    chunks = []
    total_len = len(frame_data)
    total_chunks = (total_len + UDP_MAX_PAYLOAD - 1) // UDP_MAX_PAYLOAD

    for i in range(total_chunks):
        start = i * UDP_MAX_PAYLOAD
        end = min(start + UDP_MAX_PAYLOAD, total_len)
        chunk_data = frame_data[start:end]
        packet = pack_udp_chunk(client_id, room_id, frame_id, i, total_chunks, chunk_data)
        chunks.append(packet)

    return chunks

class FrameReassembler:
    """Helper to reassemble frames from UDP chunks with timeout/drop support"""
    def __init__(self, timeout=1.0):
        self.frames = {} # (client_id, frame_id) -> {chunks: {idx: data}, total: n, timestamp: t}
        self.timeout = timeout

    def add_chunk(self, client_id: int, frame_id: int, chunk_idx: int, total_chunks: int, data: bytes) -> Optional[bytes]:
        key = (client_id, frame_id)
        now = time.time()

        # Cleanup old incomplete frames
        self._cleanup(now)

        if key not in self.frames:
            self.frames[key] = {
                'chunks': {},
                'total': total_chunks,
                'timestamp': now
            }

        frame_info = self.frames[key]
        frame_info['chunks'][chunk_idx] = data

        if len(frame_info['chunks']) == frame_info['total']:
            # All chunks received
            complete_frame = bytearray()
            for i in range(frame_info['total']):
                if i not in frame_info['chunks']:
                    # Missing chunk (should not happen if len == total, but safe-check)
                    return None
                complete_frame.extend(frame_info['chunks'][i])

            del self.frames[key]
            return bytes(complete_frame)

        return None

    def _cleanup(self, now: float):
        keys_to_del = [k for k, v in self.frames.items() if now - v['timestamp'] > self.timeout]
        for k in keys_to_del:
            del self.frames[k]

# ==== TEST BLOCK ====
if __name__ == "__main__":
    print("--- Testing UDP Protocol v2 ---")
    fake_frame = b"HEXACALL_VIDEO_DATA" * 100 # ~2KB
    cid, rid, fid = 1, 10, 99

    packets = chunk_frame(cid, rid, fid, fake_frame)
    print(f"Frame split into {len(packets)} chunks")

    reassembler = FrameReassembler()
    result = None
    for p in packets:
        unpacked = unpack_udp_chunk(p)
        if unpacked:
            c_id, r_id, f_id, c_idx, t_chunks, pld = unpacked
            result = reassembler.add_chunk(c_id, f_id, c_idx, t_chunks, pld)
            if result:
                print(f"Frame {f_id} reassembled! Size match: {len(result) == len(fake_frame)}")

    # Test corruption
    bad_data = b"wrong_magic" + packets[0][4:]
    if unpack_udp_chunk(bad_data) is None:
        print("Corruption check passed: Invalid magic dropped.")
