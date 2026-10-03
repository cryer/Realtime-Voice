"""生成 M0 回归测试用的"标准用户语音"（16kHz PCM16 mono）。

纯合成音无法触发 Silero VAD（它针对真实语音训练），所以用 Windows 自带
SAPI TTS 合成两段中文语音，ffmpeg 转 16kHz，再拼上静音段：
0.6s 静音 | 语音1 | 0.9s 静音（> endpoint 400ms，触发 speech_end）| 语音2 | 1.2s 静音
期望：2 个 speech_start + 2 个 speech_end。

用法：python scripts/make_test_wav.py [out.wav]
依赖：Windows SAPI（自带）+ ffmpeg（PATH 中）。
"""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 16000

TEXTS = [
    "你好，这是一个语音活动检测的测试，我正在说话。",
    "第二轮语音，用来验证端点检测。",
]


def tts_to_pcm16(text: str, tmpdir: str, idx: int) -> np.ndarray:
    raw = Path(tmpdir) / f"sapi_{idx}.wav"
    conv = Path(tmpdir) / f"sapi_{idx}_16k.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{raw}'); "
        f"$s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(conv)],
                   check=True)
    with wave.open(str(conv), "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "reports/test_speech.wav"
    sil = lambda s: np.zeros(int(SR * s), dtype=np.int16)
    with tempfile.TemporaryDirectory() as tmpdir:
        seg1 = tts_to_pcm16(TEXTS[0], tmpdir, 0)
        seg2 = tts_to_pcm16(TEXTS[1], tmpdir, 1)
    audio = np.concatenate([sil(0.6), seg1, sil(0.9), seg2, sil(1.2)])
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())
    print(f"wrote {out} ({len(audio)/SR:.1f}s)")


if __name__ == "__main__":
    main()
