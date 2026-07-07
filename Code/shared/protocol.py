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

# Audio Configuration
AUDIO_SAMPLE_RATE = 16000  # Hz (16 kHz)
AUDIO_CHANNELS = 1         # Mono
AUDIO_SAMPLE_WIDTH = 2     # 16-bit = 2 bytes
AUDIO_FRAME_MS = 20        # 20ms frames
AUDIO_FRAME_SIZE = int(AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS / 1000)  # 320 samples
AUDIO_BYTES_PER_FRAME = AUDIO_FRAME_SIZE * AUDIO_SAMPLE_WIDTH  # 640 bytes

class PacketType(IntEnum):
    """Protocol message types for HexaCall"""
    LOGIN = 1
    JOIN_ROOM = 2
    LEAVE_ROOM = 3
    ROOM_STATE = 4
    ERROR = 5
    CHAT = 6
    VIDEO_DATA = 7  # UDP Video chunk
    AUDIO_DATA = 8  # UDP Audio chunk

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

def recv_all(sock: socket.socket, n: int) -> Optional[bytes]:
    """Helper to receive exactly n bytes or return None if EOF"""
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except (socket.error, ConnectionResetError):
            return None
    return bytes(data)

def recv_message(sock: socket.socket) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """
    Receives a complete TCP message using framing.
    Returns (msg_type, payload_dict) or (None, None) on error/disconnect.
    """
    header_data = recv_all(sock, TCP_HEADER_SIZE)
    if not header_data:
        return None, None

    msg_type, payload_len = struct.unpack(TCP_HEADER_FORMAT, header_data)

    if payload_len > 0:
        payload_data = recv_all(sock, payload_len)
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

def pack_udp_chunk(client_id: int, room_id: int, frame_id: int, chunk_idx: int, total_chunks: int, data: bytes, pkt_type: int = PacketType.VIDEO_DATA) -> bytes:
    """Packs a video or audio chunk with its 20-byte binary header.

    Args:
        client_id: Sender's client ID (0-65535)
        room_id: Target room ID (0-65535)
        frame_id: Frame/sequence number
        chunk_idx: Current chunk index (0-based)
        total_chunks: Total chunks for this frame
        data: Payload bytes
        pkt_type: Packet type (PacketType.VIDEO_DATA or PacketType.AUDIO_DATA)
    """
    payload_len = len(data)

    # Range validation
    for name, value in {
        "client_id": client_id,
        "room_id": room_id,
        "frame_id": frame_id,
        "chunk_idx": chunk_idx,
        "total_chunks": total_chunks,
    }.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")

    if not (0 <= client_id <= 65535):
        raise ValueError(f"client_id {client_id} out of bounds")
    if not (0 <= room_id <= 65535):
        raise ValueError(f"room_id {room_id} out of bounds")
    if not (0 <= frame_id <= 4294967295):
        raise ValueError(f"frame_id {frame_id} out of bounds")
    if not (0 <= chunk_idx <= 65535):
        raise ValueError(f"chunk_idx {chunk_idx} out of bounds")
    if not (1 <= total_chunks <= 65535):
        raise ValueError(f"total_chunks {total_chunks} out of bounds")
    if payload_len > UDP_MAX_PAYLOAD:
        raise ValueError(f"payload_len {payload_len} exceeds max payload")

    header = struct.pack(
        UDP_HEADER_FORMAT,
        UDP_MAGIC,
        UDP_VERSION,
        int(pkt_type),
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
    Unpacks a video or audio chunk.
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
    if p_type not in (int(PacketType.VIDEO_DATA), int(PacketType.AUDIO_DATA)):
        return None
    if len(payload) != payload_len:
        return None

    return client_id, room_id, frame_id, chunk_idx, total_chunks, payload

def chunk_frame(client_id: int, room_id: int, frame_id: int, frame_data: bytes, pkt_type: int = PacketType.VIDEO_DATA) -> List[bytes]:
    """Splits a large frame into multiple UDP-safe chunks.

    Args:
        client_id: Sender's client ID.
        room_id: Target room ID.
        frame_id: Frame/sequence number.
        frame_data: Raw bytes to chunk.
        pkt_type: Packet type (PacketType.VIDEO_DATA or PacketType.AUDIO_DATA).
    """
    chunks = []
    total_len = len(frame_data)
    total_chunks = (total_len + UDP_MAX_PAYLOAD - 1) // UDP_MAX_PAYLOAD

    for i in range(total_chunks):
        start = i * UDP_MAX_PAYLOAD
        end = min(start + UDP_MAX_PAYLOAD, total_len)
        chunk_data = frame_data[start:end]
        packet = pack_udp_chunk(client_id, room_id, frame_id, i, total_chunks, chunk_data, pkt_type)
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
