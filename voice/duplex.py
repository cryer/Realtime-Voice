"""M2 全双工轮次：VAD endpointing 自动切轮，免按键连续对话。

用法：
    python -m voice.duplex                # 麦克风全双工（务必戴耳机，见 AGENTS.md §6）
    python -m voice.duplex --file reports/test_speech.wav --no-play   # 回归：realtime 喂帧

文件模式固定 realtime 吐帧（burst 下 VAD/延迟数字无意义）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from voice.asr import create_asr
from voice.llm import create_llm
from voice.metrics import MetricsSink, load_records, render_report
from voice.tts import create_tts
from voice.turn_manager import TurnManager
from voice.vad import SileroVAD

SYSTEM_PROMPT = "你是一个语音助手，回答简短口语化，每次不超过三句话。"


async def _close_providers(*providers) -> None:
    for p in providers:
        close = getattr(p, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass


def _make_player(args):
    if args.no_play:
        from voice.player import NullPlayer
        return NullPlayer()
    try:
        from voice.player import Player
        return Player()
    except Exception as e:
        print(f"[warn] 声卡不可用（{e}），改用 NullPlayer 落盘 reports/recordings/tts_out.wav")
        from voice.player import NullPlayer
        return NullPlayer()


async def amain(args) -> None:
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    for slot in ("asr", "llm", "tts"):
        override = getattr(args, slot)
        if override:
            cfg.setdefault("providers", {})[slot] = override

    vad_cfg = cfg.get("vad", {})
    vad = SileroVAD(vad_cfg.get("model_path", "models/silero_vad.onnx"),
                    threshold=vad_cfg.get("threshold", 0.5),
                    neg_threshold=vad_cfg.get("neg_threshold", 0.35),
                    endpoint_ms=cfg.get("endpoint_ms", 400),
                    min_speech_ms=vad_cfg.get("min_speech_ms", 96))
    asr, llm, tts = create_asr(cfg), create_llm(cfg), create_tts(cfg)
    player = _make_player(args)

    # M4 playbook ①+⑤：filler 占位音频开机预合成（顺带预热 TTS TLS/音色）
    filler_pcm = None
    filler_cfg = cfg.get("filler", {})
    if filler_cfg.get("enabled"):
        warmup = getattr(tts, "warmup", None)
        if warmup is not None:
            try:
                filler_pcm = await warmup(filler_cfg.get("text", "嗯，好的。"))
            except Exception as e:
                print(f"[warn] TTS 预热/filler 合成失败：{e}")
        if filler_pcm:
            print(f"[M4] filler 已预合成（{len(filler_pcm) // 32}ms），"
                  f"TTS 连接已预热")
        else:
            print("[M4] filler 不可用（provider 无 warmup 或合成失败），禁用")

    tm = TurnManager(vad=vad, asr=asr, llm=llm, tts=tts, player=player,
                     cfg=cfg, system_prompt=cfg.get("system_prompt", SYSTEM_PROMPT),
                     filler_pcm=filler_pcm)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = Path(args.out) / f"m2_{stamp}.jsonl"
    try:
        with MetricsSink(jsonl_path) as sink:
            if args.file:
                from voice.transport.wav_file import wav_frames
                print(f"[M2] 文件回归：{args.file}（realtime）")
                await tm.run(wav_frames(args.file, realtime=True), sink)
            else:
                from voice.transport.local_sounddevice import mic_frames
                print("[M2] 全双工：直接说话，停顿自动切轮；agent 说话时可打断"
                      "（务必戴耳机）；Ctrl+C 退出")
                await tm.run(mic_frames(), sink)
    finally:
        player.close()
        await _close_providers(asr, llm, tts)

    print(f"[M2] 会话落盘 {jsonl_path}")
    stats_fn = getattr(player, "stats", None)
    if stats_fn is not None:
        st = stats_fn()
        print(f"[泄露检查] 迟到 stale chunk 丢弃 {st['dropped_stale_chunks']} 个"
              f"（{st['dropped_stale_bytes']}B，全部未播）；"
              f"flush 清除未播 {st['flushed_bytes']}B")
    turns, _, barge_ins = load_records(jsonl_path)
    if turns:
        print(render_report(turns, barge_ins, cfg.get("budget_ms", {})))


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m voice.duplex")
    ap.add_argument("--file", help="用 wav 文件模拟用户语音（realtime 喂帧）")
    ap.add_argument("--no-play", action="store_true", help="不出声，TTS 音频落盘")
    ap.add_argument("--config", default="configs/default.json")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--asr", help="覆盖 config 的 ASR provider")
    ap.add_argument("--llm", help="覆盖 config 的 LLM provider")
    ap.add_argument("--tts", help="覆盖 config 的 TTS provider")
    args = ap.parse_args(argv)
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
