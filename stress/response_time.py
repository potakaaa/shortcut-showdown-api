import argparse
import asyncio
import aiohttp
import time
from statistics import mean

# =========================
# CONFIG (defaults can be overridden via CLI)
# =========================
URL = "http://localhost:8000/"  # frequently-used root / health endpoint
TOTAL_REQUESTS = 1000
CONCURRENT_USERS = 100

# =========================
# STORAGE
# =========================
response_times = []
success_count = 0
failure_count = 0


async def fetch(session, url, sem: asyncio.Semaphore):
    global success_count, failure_count

    start_time = time.perf_counter()
    await sem.acquire()
    try:
        async with session.get(url) as response:
            await response.text()

            elapsed = (time.perf_counter() - start_time) * 1000
            response_times.append(elapsed)

            if response.status == 200:
                success_count += 1
            else:
                failure_count += 1

    except Exception as e:
        failure_count += 1
        print("Request failed:", e)
    finally:
        try:
            sem.release()
        except Exception:
            pass


async def run_stress_test():
    connector = aiohttp.TCPConnector(limit=CONCURRENT_USERS)

    sem = asyncio.Semaphore(CONCURRENT_USERS)

    async with aiohttp.ClientSession(connector=connector) as session:

        tasks = []

        overall_start = time.perf_counter()

        for _ in range(TOTAL_REQUESTS):
            task = asyncio.create_task(fetch(session, URL, sem))
            tasks.append(task)

        await asyncio.gather(*tasks)

        overall_end = time.perf_counter()

        total_duration = overall_end - overall_start

        # =========================
        # RESULTS
        # =========================
        if response_times:
            avg_response = mean(response_times)
            max_response = max(response_times)
            min_response = min(response_times)
        else:
            avg_response = max_response = min_response = 0.0

        throughput = TOTAL_REQUESTS / total_duration

        print("\n========== STRESS TEST RESULTS ==========")
        print(f"URL: {URL}")
        print(f"Total Requests: {TOTAL_REQUESTS}")
        print(f"Concurrent Users: {CONCURRENT_USERS}")

        print("\n--- RESPONSE TIME ---")
        print(f"Average: {avg_response:.2f} ms")
        print(f"Min: {min_response:.2f} ms")
        print(f"Max: {max_response:.2f} ms")

        print("\n--- REQUESTS ---")
        print(f"Successful: {success_count}")
        print(f"Failed: {failure_count}")

        print("\n--- THROUGHPUT ---")
        print(f"{throughput:.2f} requests/sec")

        print("\n--- TOTAL TEST TIME ---")
        print(f"{total_duration:.2f} seconds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple stress test for Shortcut Showdown API")
    parser.add_argument("--url", default=URL, help="Target URL to test")
    parser.add_argument("--requests", type=int, default=TOTAL_REQUESTS, help="Total number of requests to send")
    parser.add_argument("--concurrency", type=int, default=CONCURRENT_USERS, help="Max concurrent requests")
    args = parser.parse_args()

    # allow CLI overrides
    URL = args.url
    TOTAL_REQUESTS = args.requests
    CONCURRENT_USERS = args.concurrency

    asyncio.run(run_stress_test())