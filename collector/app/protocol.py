"""Formato binário dos pacotes enviados pelo ESP32.

Pacote (little-endian):

    offset  tamanho  campo
    0       2        magic  = A5 5A
    2       2        seq    (uint16, +1 a cada pacote, dá a volta em 65535)
    4       1        count  (nº de amostras neste pacote)
    5       1        reservado (0)
    6       6*count  amostras: int16 x, int16 y, int16 z

Uma mensagem WebSocket pode conter um ou mais pacotes concatenados.
Conversão para g: raw * lsb_g (informado no "hello").
"""
from __future__ import annotations

import struct

import numpy as np

MAGIC = b"\xa5\x5a"
_HDR = struct.Struct("<2sHBB")
HDR_SIZE = _HDR.size


class ProtocolError(ValueError):
    pass


def parse_packets(buf: bytes) -> list[tuple[int, np.ndarray]]:
    """Devolve [(seq, amostras int16 com shape (count, 3)), ...]."""
    out: list[tuple[int, np.ndarray]] = []
    off, n = 0, len(buf)
    while off < n:
        if n - off < HDR_SIZE:
            raise ProtocolError("cabeçalho truncado")
        magic, seq, count, _ = _HDR.unpack_from(buf, off)
        if magic != MAGIC:
            raise ProtocolError(f"magic inválido: {magic.hex()}")
        off += HDR_SIZE
        if n - off < count * 6:
            raise ProtocolError("pacote truncado")
        arr = np.frombuffer(buf, dtype="<i2", count=count * 3, offset=off).reshape(count, 3)
        out.append((seq, arr))
        off += count * 6
    return out


def build_packet(seq: int, samples: np.ndarray) -> bytes:
    """Monta um pacote (usado pelo simulador e em testes)."""
    samples = np.ascontiguousarray(samples, dtype="<i2")
    return _HDR.pack(MAGIC, seq & 0xFFFF, len(samples), 0) + samples.tobytes()
