"""M3 验收校验：读 duplex 会话 JSONL，断言 barge-in 验收标准并打印 PASS/FAIL。

用法：python scripts/check_m3.py <session.jsonl> [--expect-bargeins 3]

断言（配合 scripts/make_bargein_wav.py 生成的回归 wav）：
1. barge_in 事件数 == 预期（3 次连续打断，不崩）；
2. 每次 mute_ms（用户真实开口 → player.flush()）落在 200–450ms（验收窗 200–400 + 调度抖动）；
3. interrupted turn 数 == barge_in 数（被打断的轮次都正确落盘）；
4. speech_start 数 == barge_in 数 + 2（首轮提问 + 180ms 短促虚警未误触发）；
5. 至少 1 个完整（未打断）turn 有 t_playback_start（最后一次打断后 agent 正常答完）。
"""

import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--expect-bargeins", type=int, default=3)
    args = ap.parse_args()

    turns, starts, barge_ins = [], 0, []
    with open(args.session, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            t = rec.get("type")
            if t == "turn":
                turns.append(rec)
            elif t == "vad_event" and rec.get("kind") == "speech_start":
                starts += 1
            elif t == "barge_in":
                barge_ins.append(rec)

    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    check("barge-in 次数", len(barge_ins) == args.expect_bargeins,
          f"{len(barge_ins)} / 预期 {args.expect_bargeins}")

    mutes = [b.get("mute_ms") for b in barge_ins]
    in_window = all(m is not None and 200 <= m <= 450 for m in mutes)
    check("开口→静音时延", in_window and bool(mutes),
          f"{mutes} ms（验收窗 200–400，容差 450）")

    interrupted = sum(1 for t in turns if t.get("interrupted"))
    check("interrupted turn 落盘", interrupted == len(barge_ins),
          f"{interrupted} / {len(barge_ins)}")

    check("虚警未误触发", starts == len(barge_ins) + 2,
          f"speech_start={starts} == barge_in({len(barge_ins)}) + 提问+虚警(2)")

    completed = [t for t in turns if not t.get("interrupted")
                 and "t_playback_start" in t.get("timestamps", {})]
    check("打断后正常答完", bool(completed),
          f"{len(completed)} 个完整 turn 有播放起点")

    print(f"M3 回归：{'ALL PASS' if all(checks) else 'FAILED'}")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
