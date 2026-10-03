"""M5w Web 应用服务端：浏览器拨通即通话。

用法：
    python -m voice.web_server [--config configs/local.json] [--port 8080]
                               [--asr sherpa|volcengine] [--tts sherpa|volcengine]

- GET /            → web/index.html（通话界面：拨通/挂断 + 频率波纹）
- GET /pcm-worklet.js → 采集端 AudioWorklet
- GET /ws          → 通话 WebSocket：上行二进制 = 16kHz PCM16 mono 32ms 帧；
                     下行二进制 = agent TTS 音频；下行 JSON = flush/eos 控制帧

每次 WS 连接 = 一通电话：独立 VAD/TurnManager/MetricsSink（reports/web_*.jsonl），
provider 实例服务级共享（ASR/TTS 的本地/云端选择由 config 或命令行独立指定）。
挂断（WS 断开）即结束会话并打印延迟报告。演示按单路通话设计。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

from voice.asr import create_asr
from voice.llm import create_llm
from voice.metrics import MetricsSink, load_records, render_report
from voice.transport.web_ws import WsPlayer, ws_frames
from voice.tts import create_tts
from voice.turn_manager import TurnManager
from voice.vad import SileroVAD

SYSTEM_PROMPT = "你是一个语音助手，回答简短口语化，每次不超过三句话。"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _make_vad(cfg: dict) -> SileroVAD:
    vad_cfg = cfg.get("vad", {})
    return SileroVAD(vad_cfg.get("model_path", "models/silero_vad.onnx"),
                     threshold=vad_cfg.get("threshold", 0.5),
                     neg_threshold=vad_cfg.get("neg_threshold", 0.35),
                     endpoint_ms=cfg.get("endpoint_ms", 400),
                     min_speech_ms=vad_cfg.get("min_speech_ms", 96))


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    cfg = app["cfg"]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    peer = request.remote
    print(f"[web] 拨入：{peer}")

    player = WsPlayer(ws)
    tm = TurnManager(vad=_make_vad(cfg), asr=app["asr"], llm=app["llm"],
                     tts=app["tts"], player=player, cfg=cfg,
                     system_prompt=cfg.get("system_prompt", SYSTEM_PROMPT))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = Path(app["out"]) / f"web_{stamp}.jsonl"
    try:
        with MetricsSink(jsonl_path) as sink:
            await tm.run(ws_frames(ws), sink)
    except Exception as e:
        print(f"[web] 会话异常结束：{e!r}")
    finally:
        player.close()

    st = player.stats()
    print(f"[web] 挂断：{peer}，会话落盘 {jsonl_path}\n"
          f"[泄露检查] stale chunk 丢弃 {st['dropped_stale_chunks']} 个"
          f"（{st['dropped_stale_bytes']}B）；flush 清除未播 {st['flushed_bytes']}B")
    turns, _, barge_ins = load_records(jsonl_path)
    if turns:
        print(render_report(turns, barge_ins, cfg.get("budget_ms", {})))
    return ws


async def on_startup(app: web.Application) -> None:
    cfg = app["cfg"]
    app["asr"] = create_asr(cfg)
    app["llm"] = create_llm(cfg)
    app["tts"] = create_tts(cfg)
    prov = cfg.get("providers", {})
    print(f"[web] providers: asr={prov.get('asr')} llm={prov.get('llm')} "
          f"tts={prov.get('tts')}")
    # TTS 开机预热（playbook ⑤）
    warmup = getattr(app["tts"], "warmup", None)
    if warmup is not None:
        try:
            await warmup("嗯。")
            print("[web] TTS 已预热")
        except Exception as e:
            print(f"[warn] TTS 预热失败：{e}")
    # 本地 ASR 预热（模型加载 + 空解码）
    asr_warmup = getattr(app["asr"], "warmup", None)
    if asr_warmup is not None:
        try:
            await asr_warmup()
            print("[web] ASR 模型已预热")
        except Exception as e:
            print(f"[warn] ASR 预热失败：{e}")


async def on_cleanup(app: web.Application) -> None:
    for key in ("asr", "llm", "tts"):
        close = getattr(app.get(key), "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m voice.web_server")
    ap.add_argument("--config", default="configs/default.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--asr", help="覆盖 config 的 ASR provider（sherpa=本地）")
    ap.add_argument("--llm", help="覆盖 config 的 LLM provider")
    ap.add_argument("--tts", help="覆盖 config 的 TTS provider（sherpa=本地）")
    args = ap.parse_args(argv)

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    for slot in ("asr", "llm", "tts"):
        override = getattr(args, slot)
        if override:
            cfg.setdefault("providers", {})[slot] = override

    app = web.Application()
    app["cfg"] = cfg
    app["out"] = args.out
    app.router.add_get("/", lambda r: web.FileResponse(WEB_DIR / "index.html"))
    app.router.add_get("/pcm-worklet.js",
                       lambda r: web.FileResponse(WEB_DIR / "pcm-worklet.js"))
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    print(f"[web] 打开 http://localhost:{args.port} 拨通电话"
          f"（局域网 http://<本机IP>:{args.port}；getUserMedia 仅 localhost/HTTPS 可用）")
    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
