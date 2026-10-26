"""Offline smoke check: bundled modules, native libraries, Tk GUI and WinMM."""
import json
from pathlib import Path
import sys
import site
import tkinter as tk
import bootstrap
import av
import cffi
import numpy
import sounddevice
import mido
import pycaption
from PIL import Image
from midi_out import devices
from app import App
root = tk.Tk()
root.withdraw()
player = App(root)
root.update()
root.destroy()
print(json.dumps({'python': sys.executable, 'isolated': sys.flags.isolated, 'user_site_enabled': site.ENABLE_USER_SITE, 'search_paths': sys.path, 'av': av.__file__, 'numpy': numpy.__file__, 'sounddevice': sounddevice.__file__, 'mido': mido.__file__, 'caption_formats': pycaption.__file__, 'pillow': Image.__file__, 'ffmpeg_libraries': av.library_versions, 'audio_decoders': {name: av.Codec(name, 'r').name for name in ('pcm_s16le', 'aac', 'mp3', 'flac', 'ape', 'alac')}, 'prores4444_encoder_available': 'prores_ks' in av.codecs_available, 'portaudio': sounddevice.get_portaudio_version(), 'audio_device_count': len(sounddevice.query_devices()), 'midi_devices': devices(), 'gui_created': True, 'midi_output_selectors': len(player.midi_boxes)}, ensure_ascii=False, indent=2))
