#!/usr/bin/env -S uv run python
"""
동시 처리 수(n) 테스트: N개 POST 후 상태 폴링해서 동시에 'processing'인 개수 확인.

사용법 (donkey 폴더에서):
  API_KEY=default-api-key API_URL=http://localhost:8000 uv run python scripts/test_concurrency.py

POST는 서로 다른 file URL로 보내서 job이 5개 생성되게 함 (멱등성 회피).
"""
import os
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx 필요: uv add httpx", file=sys.stderr)
    sys.exit(1)

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "default-api-key")
NUM_JOBS = int(os.environ.get("NUM_JOBS", "5"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "2.0"))
MAX_WAIT = int(os.environ.get("MAX_WAIT", "120"))


def main() -> None:
    # 실제 URL 1개만 주면 멱등으로 job 1개만 생성됨. 여러 개면 서로 다른 URL 목록으로.
    REAL_URL = os.environ.get(
        "TEST_AUDIO_URL",
        "https://example.com/audio/test_0.mp3",
    )
    # TEST_AUDIO_URL 하나만 있으면 1개 job만 생성 (동시성 테스트는 안 됨). 여러 URL은 공백 구분으로.
    multi_url = os.environ.get("TEST_AUDIO_URLS", "").strip()
    if multi_url:
        urls = [u.strip() for u in multi_url.split()][:NUM_JOBS]
        while len(urls) < NUM_JOBS:
            urls.append(urls[-1] if urls else REAL_URL)
    else:
        urls = [REAL_URL] * NUM_JOBS

    print(f"POST {NUM_JOBS} jobs to {API_URL} ...")
    job_ids: list[str] = []
    with httpx.Client(timeout=30.0) as client:
        for i, url in enumerate(urls):
            r = client.post(
                f"{API_URL}/ai",
                headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
                json={"file": url},
            )
            r.raise_for_status()
            body = r.json()
            jid = body.get("body", {}).get("id")
            if not jid:
                print("No job id in response:", body)
                sys.exit(1)
            job_ids.append(jid)
            print(f"  job {i+1}: {jid[:8]}...")

    print(f"\nPolling GET /ai/{{id}} every {POLL_INTERVAL}s (max {MAX_WAIT}s). Expect at most n=MAX_CONCURRENT_JOBS in 'processing'.\n")
    start = time.time()
    last_processing_count = -1
    while (time.time() - start) < MAX_WAIT:
        statuses: list[str] = []
        with httpx.Client(timeout=10.0) as client:
            for jid in job_ids:
                r = client.get(
                    f"{API_URL}/ai/{jid}",
                    headers={"X-Api-Key": API_KEY},
                )
                if r.status_code == 202:
                    statuses.append("processing")
                elif r.status_code == 200:
                    statuses.append("done")
                elif r.status_code == 500:
                    statuses.append("error")
                else:
                    statuses.append(str(r.status_code))
        processing_count = sum(1 for s in statuses if s == "processing")
        done = sum(1 for s in statuses if s == "done")
        if processing_count != last_processing_count or done == len(job_ids) or processing_count > 0:
            t = time.time() - start
            print(f"  t={t:.0f}s  processing={processing_count}  done={done}/{len(job_ids)}  -> {statuses}")
            last_processing_count = processing_count
        if done == len(job_ids):
            print("\nAll jobs completed.")
            break
        time.sleep(POLL_INTERVAL)
    else:
        print("\nTimeout.")


if __name__ == "__main__":
    main()
