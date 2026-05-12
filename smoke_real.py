"""Real harness smoke: drive /ws/session over a real socket with real audio.

Generates a 1.5s synthetic 16kHz PCM tone (fake speech) and feeds it through
the user-turn slots. Measures: time-to-first-agent-audio, total session
duration, total bytes received from edge-tts.
"""
import asyncio
import json
import math
import struct
import time

import websockets


SAMPLE_RATE = 16000
DURATION_S = 1.5


def make_pcm():
    n = int(SAMPLE_RATE * DURATION_S)
    out = bytearray()
    for i in range(n):
        # 220Hz sine wave at moderate amplitude — won't transcribe to anything
        # meaningful, but exercises the full STT pipeline.
        v = int(8000 * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE))
        out += struct.pack("<h", v)
    return bytes(out)


async def main():
    pcm = make_pcm()
    print(f"sending pcm: {len(pcm)} bytes ({DURATION_S}s @ {SAMPLE_RATE}Hz)")
    t0 = time.perf_counter()
    first_audio_t = None
    audio_bytes = 0
    msg_count = 0
    score_count = 0
    user_turn_count = 0

    async with websockets.connect("ws://127.0.0.1:8765/ws/session", max_size=None) as ws:
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
            except asyncio.TimeoutError:
                print(f"TIMEOUT after {time.perf_counter()-t0:.1f}s")
                break
            msg_count += 1
            if isinstance(raw, bytes):
                if first_audio_t is None:
                    first_audio_t = time.perf_counter() - t0
                    print(f"  [+{first_audio_t:.2f}s] first audio chunk: {len(raw)} bytes")
                audio_bytes += len(raw)
                continue

            data = json.loads(raw)
            t = time.perf_counter() - t0
            tag = data.get("type")
            print(f"  [+{t:.2f}s] <- {tag}", end="")
            if tag == "session_start":
                print(f" id={data.get('session_id')}")
            elif tag == "agent_caption":
                print(f" voice={data.get('voice')} text={data.get('text')[:50]!r}")
            elif tag == "user_prompt":
                user_turn_count += 1
                print(f" — sending {len(pcm)}B PCM + audio_end")
                await ws.send(pcm)
                await ws.send(json.dumps({"type": "user_audio_end"}))
            elif tag == "user_transcript":
                print(f" text={data.get('text')!r} conf={data.get('confidence'):.2f}")
            elif tag == "score":
                score_count += 1
                s = data["score"]
                print(f" pron={s['pronunciation']} content={s['content_score']} fluency={s['fluency']}")
            elif tag == "session_end":
                print(" — done")
                break
            else:
                print(f" {data}")

    total = time.perf_counter() - t0
    print()
    print(f"=== TOTALS ===")
    print(f"  total time:           {total:.2f}s")
    print(f"  time-to-first-audio:  {first_audio_t}")
    print(f"  audio bytes received: {audio_bytes}")
    print(f"  json messages:        {msg_count - (audio_bytes>0)}")  # rough
    print(f"  user turns sent:      {user_turn_count}")
    print(f"  scores received:      {score_count}")


if __name__ == "__main__":
    asyncio.run(main())
