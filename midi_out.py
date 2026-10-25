"""Small Windows WinMM MIDI output wrapper; no driver installation required."""
import ctypes as C
import os
from ctypes import wintypes as W

class MidiCaps(C.Structure):
    _fields_ = [('mid', W.WORD), ('pid', W.WORD), ('version', W.DWORD), ('name', W.WCHAR * 32), ('technology', W.WORD), ('voices', W.WORD), ('notes', W.WORD), ('mask', W.WORD), ('support', W.DWORD)]

class MidiHeader(C.Structure):
    _fields_ = [('data', C.c_void_p), ('length', W.DWORD), ('recorded', W.DWORD), ('user', C.c_size_t), ('flags', W.DWORD), ('next', C.c_void_p), ('reserved', C.c_size_t), ('offset', W.DWORD), ('reserved_array', C.c_size_t * 8)]

def api():
    if os.name != 'nt':
        raise RuntimeError('MIDI output requires Windows WinMM')
    lib = C.WinDLL('winmm')
    lib.midiOutGetNumDevs.restype = W.UINT
    lib.midiOutGetDevCapsW.argtypes = [C.c_size_t, C.POINTER(MidiCaps), W.UINT]
    lib.midiOutOpen.argtypes = [C.POINTER(C.c_void_p), W.UINT, C.c_size_t, C.c_size_t, W.DWORD]
    for name in ('midiOutReset', 'midiOutClose'):
        getattr(lib, name).argtypes = [C.c_void_p]
    lib.midiOutShortMsg.argtypes = [C.c_void_p, W.DWORD]
    for name in ('midiOutPrepareHeader', 'midiOutLongMsg', 'midiOutUnprepareHeader'):
        getattr(lib, name).argtypes = [C.c_void_p, C.POINTER(MidiHeader), W.UINT]
    lib.midiOutGetErrorTextW.argtypes = [W.UINT, W.LPWSTR, W.UINT]
    return lib

def devices():
    if os.name != 'nt':
        return []
    lib = api()
    result = []
    for index in range(lib.midiOutGetNumDevs()):
        caps = MidiCaps()
        if lib.midiOutGetDevCapsW(index, C.byref(caps), C.sizeof(caps)) == 0:
            result.append((index, caps.name))
    return result

class MidiOutput:

    def __init__(self, device):
        self.lib = api()
        self.handle = C.c_void_p()
        self.pending = []
        self.check(self.lib.midiOutOpen(C.byref(self.handle), device, 0, 0, 0))

    def check(self, error):
        if error:
            text = C.create_unicode_buffer(256)
            self.lib.midiOutGetErrorTextW(error, text, 256)
            raise RuntimeError(f'MIDI output error {error}: {text.value}')

    def send(self, msg):
        if not msg:
            return
        self.collect()
        if msg[0] != 240:
            self.check(self.lib.midiOutShortMsg(self.handle, int.from_bytes(msg, 'little')))
            return
        buf = C.create_string_buffer(msg)
        header = MidiHeader(data=C.cast(buf, C.c_void_p), length=len(msg))
        self.check(self.lib.midiOutPrepareHeader(self.handle, C.byref(header), C.sizeof(header)))
        try:
            self.check(self.lib.midiOutLongMsg(self.handle, C.byref(header), C.sizeof(header)))
        except Exception:
            self.lib.midiOutUnprepareHeader(self.handle, C.byref(header), C.sizeof(header))
            raise
        self.pending.append((header, buf))

    def collect(self):
        remaining = []
        for header, buf in self.pending:
            if header.flags & 1:
                self.check(self.lib.midiOutUnprepareHeader(self.handle, C.byref(header), C.sizeof(header)))
            else:
                remaining.append((header, buf))
        self.pending = remaining

    def panic(self):
        if self.handle:
            self.check(self.lib.midiOutReset(self.handle))
            self.collect()
            for channel in range(16):
                for cc in (64, 120, 123):
                    self.send(bytes([176 | channel, cc, 0]))

    def close(self):
        if self.handle:
            self.panic()
            self.collect()
            self.check(self.lib.midiOutClose(self.handle))
            self.handle = C.c_void_p()
