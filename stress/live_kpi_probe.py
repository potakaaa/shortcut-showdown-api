import argparse
import asyncio
import json
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import aiohttp


@dataclass
class MetricBucket:
    times_ms: list[float] = field(default_factory=list)
    success: int = 0
    failure: int = 0
    status_counts: dict[int, int] = field(default_factory=dict)
    error_samples: list[str] = field(default_factory=list)

    def add(self, elapsed_ms: float, ok: bool, status: int | None) -> None:
        self.times_ms.append(elapsed_ms)
        if ok:
            self.success += 1
        else:
            self.failure += 1
        if status is not None:
            self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def add_error_sample(self, sample: str, limit: int = 3) -> None:
        if len(self.error_samples) < limit:
            self.error_samples.append(sample)


def derive_ws_url(api_base: str) -> str:
    if api_base.startswith("https://"):
        return "wss://" + api_base[len("https://") :].rstrip("/") + "/ws"
    if api_base.startswith("http://"):
        return "ws://" + api_base[len("http://") :].rstrip("/") + "/ws"
    return "ws://" + api_base.rstrip("/") + "/ws"


def load_expected_keys_by_prompt() -> dict[str, list[str]]:
    try:
        from app.services.shortcut_dataset import get_default_dataset
    except Exception:
        return {}

    mapping: dict[str, list[str]] = {}
    for entry in get_default_dataset():
        prompt = entry.get("prompt")
        keys = entry.get("expectedKeys")
        if isinstance(prompt, str) and isinstance(keys, list):
            mapping[prompt] = [str(k) for k in keys]
    return mapping


def parse_int_list(raw: str) -> list[int]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    result: list[int] = []
    for item in items:
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    d0 = ordered[f] * (c - k)
    d1 = ordered[c] * (k - f)
    return d0 + d1


def summarize(name: str, bucket: MetricBucket, total_seconds: float) -> str:
    total = bucket.success + bucket.failure
    avg = sum(bucket.times_ms) / len(bucket.times_ms) if bucket.times_ms else 0.0
    p50 = percentile(bucket.times_ms, 50)
    p95 = percentile(bucket.times_ms, 95)
    mn = min(bucket.times_ms) if bucket.times_ms else 0.0
    mx = max(bucket.times_ms) if bucket.times_ms else 0.0
    err_rate = (bucket.failure / total) * 100 if total else 0.0
    throughput = total / total_seconds if total_seconds > 0 else 0.0

    status_parts = []
    for code in sorted(bucket.status_counts.keys()):
        status_parts.append(f"{code}:{bucket.status_counts[code]}")
    status_line = f"  status_counts: {', '.join(status_parts)}" if status_parts else ""

    parts = [
        f"{name}",
        f"  requests: {total} (ok: {bucket.success}, fail: {bucket.failure})",
        f"  error_rate: {err_rate:.2f}%",
        f"  response_ms: avg {avg:.2f}, p50 {p50:.2f}, p95 {p95:.2f}, min {mn:.2f}, max {mx:.2f}",
        f"  throughput: {throughput:.2f} req/s",
    ]
    if status_line:
        parts.append(status_line)
    return "\n".join(parts)


async def timed_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    bucket: MetricBucket,
    json_body: Any | None = None,
) -> tuple[int | None, str | None]:
    start = time.perf_counter()
    status: int | None = None
    text: str | None = None
    ok = False
    try:
        async with session.request(method, url, json=json_body) as res:
            status = res.status
            text = await res.text()
            ok = 200 <= res.status < 300
    except Exception:
        ok = False
    elapsed_ms = (time.perf_counter() - start) * 1000
    bucket.add(elapsed_ms, ok, status)
    if not ok:
        body = text if text is not None else "<no body>"
        bucket.add_error_sample(f"status={status}, body={body[:200]}")
    return status, text


async def run_workflow(
    session: aiohttp.ClientSession,
    api_base: str,
    ws_url: str,
    metrics: dict[str, MetricBucket],
    display_name: str,
    players_per_room: int,
    attempts_per_workflow: int,
    attempt_delay_ms: int,
    expected_keys_by_prompt: dict[str, list[str]],
) -> None:
    ws_bucket = metrics.setdefault("ws_connect", MetricBucket())
    player_ids: list[str] = []

    try:
        async with AsyncExitStack() as stack:
            sockets = []
            for _ in range(max(1, players_per_room)):
                start = time.perf_counter()
                ws = await stack.enter_async_context(session.ws_connect(ws_url))
                msg = await ws.receive_json()
                player_id = msg.get("player_id")
                ok = bool(player_id)
                elapsed_ms = (time.perf_counter() - start) * 1000
                ws_bucket.add(elapsed_ms, ok, None)
                if not player_id:
                    return
                sockets.append(ws)
                player_ids.append(player_id)

            for idx, player_id in enumerate(player_ids):
                await timed_request(
                    session,
                    "PATCH",
                    f"{api_base}/players/{player_id}",
                    metrics.setdefault("PATCH /players/{id}", MetricBucket()),
                    {"display_name": f"{display_name}_{idx + 1}"},
                )

            _, lobby_text = await timed_request(
                session,
                "POST",
                f"{api_base}/lobbies",
                metrics.setdefault("POST /lobbies", MetricBucket()),
                {"player_id": player_ids[0]},
            )

            lobby_id = None
            if lobby_text:
                try:
                    lobby_id = json.loads(lobby_text).get("id")
                except Exception:
                    lobby_id = None

            if not lobby_id:
                return

            if players_per_room > 2:
                await timed_request(
                    session,
                    "POST",
                    f"{api_base}/lobbies/{lobby_id}/set-max-players",
                    metrics.setdefault("POST /lobbies/{id}/set-max-players", MetricBucket()),
                    {
                        "player_id": player_ids[0],
                        "max_players": players_per_room,
                    },
                )

            for player_id in player_ids[1:]:
                await timed_request(
                    session,
                    "POST",
                    f"{api_base}/lobbies/{lobby_id}/join",
                    metrics.setdefault("POST /lobbies/{id}/join", MetricBucket()),
                    {"player_id": player_id},
                )

            await timed_request(
                session,
                "GET",
                f"{api_base}/lobbies/{lobby_id}",
                metrics.setdefault("GET /lobbies/{id}", MetricBucket()),
            )

            await timed_request(
                session,
                "POST",
                f"{api_base}/lobbies/{lobby_id}/start",
                metrics.setdefault("POST /lobbies/{id}/start", MetricBucket()),
                {"player_id": player_ids[0]},
            )

            _, room_text = await timed_request(
                session,
                "GET",
                f"{api_base}/game-rooms/{lobby_id}",
                metrics.setdefault("GET /game-rooms/{id}", MetricBucket()),
            )

            if attempts_per_workflow <= 0:
                return

            state: dict[str, Any] | None = None
            if room_text:
                try:
                    room_data = json.loads(room_text)
                    state = room_data.get("game_state")
                except Exception:
                    state = None

            if not isinstance(state, dict):
                return

            attempt_bucket = metrics.setdefault(
                "POST /game-rooms/{id}/attempts", MetricBucket()
            )
            for attempt_idx in range(attempts_per_workflow):
                players_state = state.get("players") if isinstance(state, dict) else {}
                player_state = (
                    players_state.get(player_ids[0])
                    if isinstance(players_state, dict)
                    else {}
                )
                objective_index = 0
                if isinstance(player_state, dict):
                    objective_index = int(player_state.get("objective_index", 0))

                challenges = state.get("challenges") if isinstance(state, dict) else []
                keys = ["ctrl", "x"]
                if isinstance(challenges, list) and objective_index < len(challenges):
                    prompt = challenges[objective_index].get("prompt")
                    if isinstance(prompt, str):
                        keys = expected_keys_by_prompt.get(prompt, keys)

                attempt_id = f"{player_ids[0]}-{attempt_idx}-{int(time.time() * 1000)}"
                _, attempt_text = await timed_request(
                    session,
                    "POST",
                    f"{api_base}/game-rooms/{lobby_id}/attempts",
                    attempt_bucket,
                    {
                        "player_id": player_ids[0],
                        "objective_index": objective_index,
                        "keys": keys,
                        "attempt_id": attempt_id,
                    },
                )

                if attempt_text:
                    try:
                        attempt_data = json.loads(attempt_text)
                        next_state = attempt_data.get("game_state")
                        if isinstance(next_state, dict):
                            state = next_state
                    except Exception:
                        pass

                if attempt_delay_ms > 0:
                    await asyncio.sleep(attempt_delay_ms / 1000.0)
    except Exception:
        return


async def run_health_load(
    session: aiohttp.ClientSession,
    api_base: str,
    metrics: dict[str, MetricBucket],
    total: int,
    concurrency: int,
) -> None:
    bucket = metrics.setdefault("GET /", MetricBucket())
    sem = asyncio.Semaphore(concurrency)

    async def one() -> None:
        async with sem:
            await timed_request(session, "GET", f"{api_base}/", bucket)

    await asyncio.gather(*[asyncio.create_task(one()) for _ in range(total)])


async def run_scenario(
    session: aiohttp.ClientSession,
    api_base: str,
    ws_url: str,
    display_name: str,
    health_requests: int,
    health_concurrency: int,
    workflows: int,
    workflow_concurrency: int,
    label: str,
    players_per_room: int,
    attempts_per_workflow: int,
    attempt_delay_ms: int,
) -> None:
    metrics: dict[str, MetricBucket] = {}
    expected_keys_by_prompt = load_expected_keys_by_prompt()

    overall_start = time.perf_counter()

    health_start = time.perf_counter()
    await run_health_load(
        session,
        api_base,
        metrics,
        total=health_requests,
        concurrency=health_concurrency,
    )
    health_seconds = time.perf_counter() - health_start

    workflow_start = time.perf_counter()
    workflow_sem = asyncio.Semaphore(workflow_concurrency)

    async def one_workflow() -> None:
        async with workflow_sem:
            await run_workflow(
                session,
                api_base,
                ws_url,
                metrics,
                display_name=display_name,
                players_per_room=players_per_room,
                attempts_per_workflow=attempts_per_workflow,
                attempt_delay_ms=attempt_delay_ms,
                expected_keys_by_prompt=expected_keys_by_prompt,
            )

    await asyncio.gather(*[asyncio.create_task(one_workflow()) for _ in range(workflows)])
    workflow_seconds = time.perf_counter() - workflow_start

    overall_seconds = time.perf_counter() - overall_start

    print("\n========== LIVE KPI PROBE ==========")
    print(f"Scenario: {label}")
    print(f"API base: {api_base}")
    print(f"WS url:  {ws_url}")
    print(f"Health requests: {health_requests} @ concurrency {health_concurrency}")
    print(f"Workflow runs:   {workflows} @ concurrency {workflow_concurrency}")

    print("\n--- PER ENDPOINT ---")
    for name in sorted(metrics.keys()):
        bucket = metrics[name]
        if name == "GET /":
            total_seconds = health_seconds
        else:
            total_seconds = workflow_seconds
        print(summarize(name, bucket, total_seconds))
        if bucket.error_samples:
            print("  error_samples:")
            for sample in bucket.error_samples:
                print(f"    - {sample}")

    all_bucket = MetricBucket()
    for bucket in metrics.values():
        for t in bucket.times_ms:
            all_bucket.times_ms.append(t)
        all_bucket.success += bucket.success
        all_bucket.failure += bucket.failure

    print("\n--- CUMULATIVE ---")
    print(summarize("ALL", all_bucket, overall_seconds))


async def run_all(args: argparse.Namespace) -> None:
    api_base = args.api_base.rstrip("/")
    ws_url = args.ws_url or derive_ws_url(api_base)
    timeout = aiohttp.ClientTimeout(total=args.timeout)

    scenarios = [
        (
            "single",
            args.health_requests,
            args.health_concurrency,
            args.workflows,
            args.workflow_concurrency,
            args.players_per_room,
        )
    ]
    if args.matrix:
        players_list = parse_int_list(args.players_matrix)
        workflow_concurrency_list = parse_int_list(args.workflow_concurrency_matrix)
        if not players_list:
            players_list = [2, 4]
        if not workflow_concurrency_list:
            workflow_concurrency_list = [5, 10, 20]

        scenarios = []
        for players in players_list:
            for wf_conc in workflow_concurrency_list:
                label = f"p{players}-rooms{wf_conc}"
                scenarios.append(
                    (
                        label,
                        args.health_requests,
                        args.health_concurrency,
                        args.workflows,
                        wf_conc,
                        players,
                    )
                )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for label, h_req, h_conc, wf_runs, wf_conc, players in scenarios:
            await run_scenario(
                session,
                api_base,
                ws_url,
                args.display_name,
                h_req,
                h_conc,
                wf_runs,
                wf_conc,
                label,
                players,
                args.attempts_per_workflow,
                args.attempt_delay_ms,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure live API throughput, response time, and error rate."
    )
    parser.add_argument(
        "--api-base",
        default="https://shortcut-showdown-api.onrender.com",
        help="API base URL (no trailing slash)",
    )
    parser.add_argument(
        "--ws-url",
        default="",
        help="Override WebSocket URL (defaults derived from api-base)",
    )
    parser.add_argument(
        "--health-requests",
        type=int,
        default=200,
        help="Total GET / requests",
    )
    parser.add_argument(
        "--health-concurrency",
        type=int,
        default=50,
        help="Concurrent GET / requests",
    )
    parser.add_argument(
        "--workflows",
        type=int,
        default=50,
        help="Number of lobby workflow runs",
    )
    parser.add_argument(
        "--workflow-concurrency",
        type=int,
        default=10,
        help="Concurrent lobby workflows",
    )
    parser.add_argument(
        "--players-per-room",
        type=int,
        default=2,
        help="Number of players per lobby (1-2 recommended)",
    )
    parser.add_argument(
        "--attempts-per-workflow",
        type=int,
        default=5,
        help="Number of gameplay attempts per workflow",
    )
    parser.add_argument(
        "--attempt-delay-ms",
        type=int,
        default=50,
        help="Delay between attempts in milliseconds",
    )
    parser.add_argument(
        "--display-name",
        default="PERF_BOT",
        help="Display name for test player",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run a grid over players per room and concurrent workflows",
    )
    parser.add_argument(
        "--players-matrix",
        default="2,4",
        help="Comma-separated players per room for matrix runs",
    )
    parser.add_argument(
        "--workflow-concurrency-matrix",
        default="5,10,20",
        help="Comma-separated concurrent rooms for matrix runs",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_all(parse_args()))
