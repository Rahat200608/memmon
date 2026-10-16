"""memmon - универсальный монитор памяти/CPU для любой Python-программы."""
import atexit
import os
import threading
import time
import tracemalloc
from datetime import datetime

import psutil

_started = False


def _rss_mb(proc, children):
    total = proc.memory_info().rss
    if children:
        for c in proc.children(recursive=True):
            try:
                total += c.memory_info().rss
            except psutil.Error:
                pass
    return total / 1024 / 1024


def _conn_count(proc):
    try:
        fn = getattr(proc, "net_connections", None) or proc.connections
        return len(fn())
    except Exception:
        return -1


def start(interval=None, path=None, children=True, trace=None):
    """Запускает фоновый замер. Повторный вызов ничего не делает."""
    global _started
    if _started:
        return
    _started = True

    interval = float(interval or os.getenv("MEMMON_INTERVAL", 10))
    path = path or os.getenv("MEMMON_FILE", f"memmon_{os.getpid()}.csv")
    if trace is None:
        trace = os.getenv("MEMMON_TRACE") == "1"

    proc = psutil.Process()
    peak = [0.0]

    if trace:
        tracemalloc.start(5)

    def write(line, file=path):
        with open(file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def loop():
        proc.cpu_percent(None)
        prev = None
        write("time;rss_mb;peak_mb;cpu_pct;threads;connections")
        while True:
            time.sleep(interval)
            try:
                rss = _rss_mb(proc, children)
                peak[0] = max(peak[0], rss)
                write(
                    f"{datetime.now():%H:%M:%S};{rss:.1f};{peak[0]:.1f};"
                    f"{proc.cpu_percent(None):.0f};{proc.num_threads()};{_conn_count(proc)}"
                )
                if trace:
                    snap = tracemalloc.take_snapshot()
                    if prev is not None:
                        for s in snap.compare_to(prev, "traceback")[:5]:
                            if s.size_diff > 0:
                                write(
                                    f"[{datetime.now():%H:%M:%S}] +{s.size_diff/1024:.0f} KB, "
                                    f"{s.count_diff} объектов\n"
                                    + "\n".join("   " + l for l in s.traceback.format(limit=4)),
                                    path + ".trace.txt",
                                )
                    prev = snap
            except psutil.NoSuchProcess:
                break
            except Exception as e:
                write(f"# monitor error: {e}")

    threading.Thread(target=loop, daemon=True, name="memmon").start()
    atexit.register(lambda: write(f"# peak_mb={peak[0]:.1f}"))
