"""Verified MI3 decompression and MDT event reading."""
import struct

class Bits:

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        v = 0
        for _ in range(n):
            if self.pos >= len(self.data) * 8:
                raise EOFError('compressed input exhausted')
            v = v << 1 | self.data[self.pos // 8] >> 7 - self.pos % 8 & 1
            self.pos += 1
        return v

def decompress(data, size):
    b = Bits(data)
    nodes = 0

    def tree():
        nonlocal nodes
        if b.read(1):
            nodes += 1
            if nodes > 255:
                raise ValueError('invalid Huffman tree')
            return (tree(), tree())
        return b.read(8)
    root = tree()

    def sym():
        t = root
        while isinstance(t, tuple):
            t = t[b.read(1)]
        return t
    ring = bytearray(b' ' * 8192)
    wp = 7166
    out = bytearray()

    def put(v):
        nonlocal wp
        if len(out) >= size:
            return
        out.append(v)
        ring[wp] = v
        wp = wp + 1 & 8191
    while len(out) < size:
        flags = sym()
        for bit in range(8):
            if len(out) >= size:
                break
            if flags >> bit & 1:
                put(sym())
            else:
                x = sym()
                if x & 1:
                    y, z = (sym(), sym())
                    distance = (x & 62) >> 1 | y << 5
                    length = ((x & 192) >> 6) + (z << 2) + 3
                else:
                    distance = (x & 14) >> 1 | sym() << 3
                    length = (x >> 4) + 3
                start = wp - distance & 8191
                for j in range(length):
                    put(ring[start + j & 8191])
    return (bytes(out), b.pos, nodes)

def parse_streams(data):
    version = data[3]
    count = 35 if version == 3 else 51
    width = 1 if version == 3 else 2
    if len(data) < 64 + 4 * count:
        raise ValueError('short MDT offset table')
    offsets = list(struct.unpack_from('<' + 'I' * count, data, 64))
    result = []
    if any((o < 64 + count * 4 or o >= len(data) for o in offsets)):
        raise ValueError('invalid stream pointer')
    for i, start in enumerate(offsets):
        p = start
        t = 0
        ev = []
        limit = min([o for o in offsets if o > start] or [len(data)])
        while p < limit and data[p]:
            c = data[p]
            n = c & 15
            if n < width or p + n + 1 > limit:
                raise ValueError(f'bad record stream {i} offset {p:#x}')
            dt = int.from_bytes(data[p + 1:p + 1 + width], 'little')
            t += dt
            ev.append((t, c >> 4, data[p + 1 + width:p + n + 1], p))
            p += n + 1
        if p >= limit:
            raise ValueError(f'missing end marker in stream {i}')
        result.append(ev)
    return result
