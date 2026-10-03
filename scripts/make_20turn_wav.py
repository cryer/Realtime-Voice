"""生成 M4 延迟达标验收用的 20 轮对话 wav（16kHz PCM16 mono）。

20 个简短中文问题（SAPI TTS 合成），每个问题后留 gap 静音让 agent 答完。
文本刻意不带逗号/句号：SAPI 在标点处停顿 >300ms，会被 endpoint 切成两轮
（M3 经验）。agent 回答长度由 bench 配置的 system_prompt 限制（一句话
≤30 字 ≈ 7s 音频），gap 默认 10s 够用。

用法：python scripts/make_20turn_wav.py [out.wav] [--gap 10.0]
依赖：Windows SAPI（自带）+ ffmpeg（PATH 中）。
"""

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from make_test_wav import tts_to_pcm16  # noqa: E402

SR = 16000

TEXTS = [
    "今天天气怎么样",
    "给我讲个笑话吧",
    "北京和上海哪个城市更大",
    "怎么做番茄炒蛋",
    "推荐一首好听的歌",
    "地球离月亮有多远",
    "怎么提高睡眠质量",
    "熊猫最喜欢吃什么",
    "海水为什么是咸的",
    "世界上最高的山是哪座",
    "咖啡喝多了会怎么样",
    "怎样缓解眼睛疲劳",
    "恐龙是怎么灭绝的",
    "手机耗电快怎么办",
    "为什么天空是蓝色的",
    "怎么煮出好吃的米饭",
    "猫的寿命一般有多长",
    "下雨天适合做什么运动",
    "人类为什么要睡觉",
    "怎样才能记住更多单词",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="reports/test_20turn.wav")
    ap.add_argument("--gap", type=float, default=10.0,
                    help="每轮问题后的静音秒数（要盖住 agent 回答时长）")
    args = ap.parse_args()
    sil = lambda s: np.zeros(int(SR * s), dtype=np.int16)
    import tempfile
    parts = [sil(0.6)]
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, text in enumerate(TEXTS):
            parts.append(tts_to_pcm16(text, tmpdir, i))
            parts.append(sil(args.gap))
    parts.append(sil(1.2))
    audio = np.concatenate(parts)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(args.out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())
    print(f"wrote {args.out} ({len(audio)/SR:.1f}s, {len(TEXTS)} turns, gap={args.gap}s)")


if __name__ == "__main__":
    main()
