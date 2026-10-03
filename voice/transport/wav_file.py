"""WAV 文件输入：固定录音当"标准用户语音"，回归测试不依赖真人说话。

要求 16kHz PCM16 mono（用 ffmpeg 转换：ffmpeg -i in.wav -ar 16000 -ac 1 -f s16le out.wav 的 wav 版）。
realtime=True 时按真实速率吐帧，模拟在线场景。
"""

from __future__ import annotations

import asyncio
import wave
from typing import AsyncIterator

FRAME_SAMPLES = 512


async def wav_frames(path: str, realtime: bool = False) -> AsyncIterator[bytes]:
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError(
                f"{path}: 需要 16kHz PCM16 mono，实际 "
                f"{wf.getframerate()}Hz/{wf.getnchannels()}ch/{wf.getsampwidth()*8}bit")
        while True:
            data = wf.readframes(FRAME_SAMPLES)
            if not data:
                break
            if len(data) < FRAME_SAMPLES * 2:
                data = data + b"\x00" * (FRAME_SAMPLES * 2 - len(data))
            yield data
            if realtime:
                await asyncio.sleep(FRAME_SAMPLES / 16000.0)
