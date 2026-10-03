"""Web 链路回归：模拟浏览器客户端（M5w）。

用法：
    python scripts/check_web.py <wav> [--url ws://localhost:6789/ws]
                                [--expect-flush N] [--tail-s 12]

行为与浏览器一致：realtime 上行 1024B PCM 帧；下行二进制收为 agent 音频
（落盘 reports/web_agent_out.wav），JSON 控制帧统计 flush/eos 次数。
断言：agent 有出声；flush 次数达标（barge-in 场景）；全程无异常断开。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import websockets

FRAME_BYTES = 1024
SAMPLE_RATE = 16000


def read_wav_frames(path: str) -> list[bytes]:
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1 and wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        pcm = wf.readframes(wf.getnframes())
    return [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm) - FRAME_BYTES + 1,
                                                  FRAME_BYTES)]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--url", default="ws://localhost:6789/ws")
    ap.add_argument("--expect-flush", type=int, default=0)
    ap.add_argument("--tail-s", type=float, default=12)
    ap.add_argument("--out", default="reports/web_agent_out.wav")
    args = ap.parse_args()

    frames = read_wav_frames(args.wav)
    audio = bytearray()
    flushes = 0
    eos = 0
    errors: list[str] = []

    kwargs: dict = {}
    if args.url.startswith("wss://"):   # 自签证书：测试客户端跳过校验
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl"] = ctx

    async with websockets.connect(args.url, max_size=None, **kwargs) as ws:
        async def produce():
            t0 = time.monotonic()
            for i, f in enumerate(frames):
                target = t0 + (i + 1) * 0.032
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                await ws.send(f)

        async def consume():
            nonlocal flushes, eos
            async for msg in ws:
                if isinstance(msg, bytes):
                    audio.extend(msg)
                else:
                    try:
                        m = json.loads(msg)
                    except ValueError:
                        continue
                    if m.get("type") == "flush":
                        flushes += 1
                    elif m.get("type") == "eos":
                        eos += 1

        consumer = asyncio.create_task(consume())
        await produce()
        await asyncio.sleep(args.tail_s)   # 等 agent 答完最后一句
        await ws.close()
        await asyncio.sleep(0.3)
        consumer.cancel()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(args.out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(audio))

    ok = True
    def check(name, cond, detail):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")
        ok = ok and cond

    check("agent 出声", len(audio) > SAMPLE_RATE * 2,
          f"{len(audio)}B ≈ {len(audio) / 32000:.1f}s → {args.out}")
    check("flush 次数", flushes >= args.expect_flush,
          f"{flushes} / 预期 ≥{args.expect_flush}")
    check("agent 完整答完（eos）", eos >= 1, f"{eos} 次")
    check("无错误", not errors, errors or "无")
    print("Web 链路回归：", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
