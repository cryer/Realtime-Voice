"""生成 M3 barge-in 回归测试 wav（16kHz PCM16 mono）。

结构（与 configs/m3_mock.json 的长回复配套，agent 每次回复 ~10s+ 音频）：
0.6s 静音 | 提问 | 3.0s 静音 | 250ms 短促语音（虚警，< 200ms 确认窗，不应触发 barge-in）
| 2.0s 静音 | 打断1 | 5.5s 静音 | 打断2 | 5.5s 静音 | 打断3 | 14s 静音（让最后一轮答完）

预期：3 次 barge-in，0 次虚警误触发，5 个 speech_start（提问+短促+3 打断）。

用法：python scripts/make_bargein_wav.py [out.wav]
依赖：Windows SAPI（自带）+ ffmpeg（PATH 中）。
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_test_wav import tts_to_pcm16  # noqa: E402

SR = 16000

QUESTION = "你好给我讲一个关于程序员的长故事"
INTERRUPTS = [
    "停一下先别讲了",
    "等等我再打断一次",
    "第三次打断你",
]
BLIP_TEXT = "啊"
BLIP_MS = 250


def make_blip(tmpdir: str) -> np.ndarray:
    """< 200ms 确认窗的短促语音（咳嗽/键盘声的代理），尾部淡出防爆音。"""
    pcm = tts_to_pcm16(BLIP_TEXT, tmpdir, 90)
    n = SR * BLIP_MS // 1000
    pcm = pcm[:n].copy()
    fade = SR * 20 // 1000
    if len(pcm) > fade:
        pcm[-fade:] = (pcm[-fade:] * np.linspace(1, 0, fade)).astype(np.int16)
    return pcm


def main() -> None:
    import tempfile
    out = sys.argv[1] if len(sys.argv) > 1 else "reports/test_bargein.wav"
    sil = lambda s: np.zeros(int(SR * s), dtype=np.int16)
    with tempfile.TemporaryDirectory() as tmpdir:
        segs = [sil(0.6), tts_to_pcm16(QUESTION, tmpdir, 0), sil(3.0),
                make_blip(tmpdir), sil(2.0)]
        for i, text in enumerate(INTERRUPTS):
            segs.append(tts_to_pcm16(text, tmpdir, i + 1))
            segs.append(sil(5.5 if i < len(INTERRUPTS) - 1 else 14.0))
    audio = np.concatenate(segs)
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())
    print(f"wrote {out} ({len(audio)/SR:.1f}s)")


if __name__ == "__main__":
    main()
