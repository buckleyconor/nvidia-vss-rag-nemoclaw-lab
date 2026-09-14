#!/usr/bin/env python3
"""shim-stream-check.py — the auth-shim streaming gate (02 step 1; 09 L5 item 1).

Usage: shim-stream-check.py <model-id> [base-url]   (base-url default http://127.0.0.1:8080)

Streams one chat completion through the shim and times each SSE `data:`
chunk as it arrives. With proxy_buffering off the chunks are spread over
the generation; with buffering on nginx releases them in one burst, so the
span between the first and last chunk collapses to ~0. Response-header
timing cannot tell the two apart (nginx forwards headers before it buffers
the body), which is why the chunks themselves are timed.

Exit 0 and print "<n> chunks over <s>s" when streaming is incremental;
exit 1 with the reason otherwise. Stdlib only; no key material is involved
(the shim substitutes the real x-api-key).
"""

import json
import sys
import time
import urllib.request

MIN_CHUNKS = 5
MIN_SPAN_S = 0.2


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: shim-stream-check.py <model-id> [base-url]", file=sys.stderr)
        return 2
    model = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8080"
    body = json.dumps({
        "model": model,
        "stream": True,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": "Count from 1 to 60, one number per line."}],
    }).encode()
    req = urllib.request.Request(
        f"{base}/v1/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
    )
    first = last = None
    chunks = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                if not line.startswith(b"data:") or b"[DONE]" in line:
                    continue
                now = time.monotonic()
                chunks += 1
                if first is None:
                    first = now
                last = now
    except Exception as exc:  # noqa: BLE001 — any failure is a failed gate
        print(f"request failed: {exc.__class__.__name__}: {exc}")
        return 1
    if chunks < MIN_CHUNKS:
        print(f"only {chunks} SSE chunk(s) received (want >= {MIN_CHUNKS})")
        return 1
    span = last - first
    if span < MIN_SPAN_S:
        print(f"all {chunks} chunks arrived within {span:.3f}s — the response is buffered")
        return 1
    print(f"{chunks} chunks over {span:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
