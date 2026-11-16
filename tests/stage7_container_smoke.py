"""CI-only runtime checks. Only container loopback and synthetic credentials."""
import concurrent.futures
import json
import os
import socket
import statistics
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
FAKE = "stage7-synthetic-only-000000000000000000000000"


def status(path, *, data=None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def percentile(values, pct):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, (len(ordered) * pct + 99) // 100 - 1)], 3)


def limits():
    with open("/proc/1/status", encoding="utf-8") as f:
        lines = dict(row.strip().split(":", 1) for row in f if ":" in row)
    assert lines["Uid"].split()[0] == "10001", "App process not non-root"
    assert int(lines["CapEff"].strip(), 16) == 0, "Effective capabilities remain"
    assert int(lines["CapPrm"].strip(), 16) == 0, "Permitted capabilities remain"
    assert lines["NoNewPrivs"].strip() == "1", "Privilege elevation not blocked"
    assert os.geteuid() == 10001
    assert os.environ.get("PVP_OBSERVED_SEARCH_ENABLED") != "1"
    assert os.stat("/data").st_uid == 10001
    def read(path):
        try:
            return open(path, encoding="ascii").read().strip()
        except FileNotFoundError:
            return "unknown"
    memory, pid_max, cpu_max = (
        read("/sys/fs/cgroup/memory.max"), read("/sys/fs/cgroup/pids.max"),
        read("/sys/fs/cgroup/cpu.max"))
    if memory != "unknown":
        assert memory == str(768 * 1024 * 1024), memory
    if pid_max != "unknown":
        assert pid_max == "128", pid_max
    if cpu_max != "unknown":
        assert cpu_max.split()[0] == cpu_max.split()[1], cpu_max
    # No DNS or external internet is needed to boot or serve the app.
    try:
        with socket.create_connection(("192.0.2.1", 443), timeout=0.25):
            raise AssertionError("Outbound connection unexpectedly succeeded")
    except OSError:
        pass
    return {"memory_max": memory, "pids_max": pid_max, "cpu_max": cpu_max}


def security():
    code, body = status("/health")
    assert code == 200, (code, body[:200])
    code, body = status("/app")
    assert code == 200, (code, body[:200])
    assert FAKE.encode() not in body, "Synthetic gateway key leaked in public HTML"
    for path in ("/app-api/sandbox", "/app-api/missing-analysis", "/mcp"):
        code, body = status(path, data=b"{}", headers={"Content-Type": "application/json"})
        assert code == 401, (path, code, body[:150])
        assert FAKE.encode() not in body
    # Host checks on the internal bearer-token endpoint prevent DNS rebind.
    req = urllib.request.Request("http://127.0.0.1:8765/api/status",
                                 headers={"Host": "evil.invalid"})
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    assert code == 403, code


def load():
    def hit(_):
        start = time.perf_counter()
        code, body = status("/health")
        assert code == 200 and b'"ok"' in body, (code, body)
        return (time.perf_counter() - start) * 1000
    # Exactly 16 requests with 4 workers; no synthetic denial-of-service.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        times = list(pool.map(hit, range(16)))
    return {"endpoint": "GET /health only", "requests": len(times),
            "concurrency": 4, "p50_ms": percentile(times, 50),
            "p95_ms": percentile(times, 95)}


if __name__ == "__main__":
    observed = {"limits": limits()}
    security()
    observed["loopback_health"] = load()
    for name in ("memory.current", "memory.peak", "cpu.stat"):
        path = "/sys/fs/cgroup/" + name
        if os.path.exists(path):
            with open(path, encoding="ascii") as stream:
                value = stream.read().strip()
            if name == "cpu.stat":
                observed["cpu_usage_usec"] = next(
                    (int(line.split()[1]) for line in value.splitlines()
                     if line.startswith("usage_usec ")), None)
            else:
                observed[name.replace(".", "_")] = value
    print("STAGE7_CONTAINER_RESULT " + json.dumps(observed, sort_keys=True))
