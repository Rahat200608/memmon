"""memmon - универсальный монитор памяти/CPU для любой Python-программы."""
import atexit
import os
import re
import sys
import threading
import time
import tracemalloc
from datetime import datetime

import psutil

_started = False
_config = {}
HEADER = "время;память_МБ;процессор_%;потоки;соединения"


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


def _place(frame):
    """Короткое место в коде: файл:строка (без длинных путей)."""
    f = frame.filename.replace("\\", "/")
    for marker in ("site-packages/", "/Lib/"):
        if marker in f:
            f = f.split(marker, 1)[1]
            break
    else:
        f = os.path.basename(f)
    return f"{f}:{frame.lineno}"


def _noise_filters():
    """Не показываем места, которые относятся к самой трассировке."""
    return [
        tracemalloc.Filter(False, tracemalloc.__file__),
        tracemalloc.Filter(False, __file__),
        tracemalloc.Filter(False, "*linecache.py"),
        tracemalloc.Filter(False, "<frozen *"),
    ]


def _script_name():
    arg = sys.argv[0] if sys.argv and sys.argv[0] else "python"
    name = os.path.splitext(os.path.basename(arg))[0] or "python"
    return re.sub(r"[^\w\-]", "_", name)


def start(interval=None, path=None, children=True, trace=None):
    """Запускает фоновый замер. Повторный вызов настроек не меняет."""
    global _started
    if _started:
        if any(v is not None for v in (interval, path, trace)):
            print(
                f"[memmon] уже запущен (интервал {_config['interval']:g} с, трассировка "
                f"{'вкл' if _config['trace'] else 'выкл'}). Новые настройки проигнорированы: "
                "убери лишний `import memmon.auto` или поставь свой memmon.start(...) раньше него.",
                file=sys.stderr,
            )
        return
    _started = True

    interval = float(interval or os.getenv("MEMMON_INTERVAL", 10))
    name = _script_name()
    path = path or os.getenv("MEMMON_FILE", f"memmon_{name}_{os.getpid()}.csv")
    if trace is None:
        trace = os.getenv("MEMMON_TRACE") == "1"
    _config.update(interval=interval, trace=trace)

    proc = psutil.Process()
    t0 = time.time()
    stats = {"first": None, "last": None, "peak": 0.0, "t_first": None, "t_last": None}

    tr = {"base": None, "last": None}
    tpath = path + ".trace.txt"
    if trace:
        tracemalloc.start(5)
        with open(tpath, "a", encoding="utf-8") as f:
            f.write(
                "# Как читать: каждая строка это место в коде, где память выросла С НАЧАЛА замера "
                "(не за последний интервал).\n"
                "# Если одно и то же место растёт из замера в замер, это кандидат на утечку.\n"
                "# Строки самой трассировки (memmon, tracemalloc, linecache) и мелочи меньше 10 КБ скрыты.\n"
            )

    def write(line, file=path):
        with open(file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # BOM нужен, чтобы Excel правильно показал русские буквы в заголовке
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "a", encoding="utf-8-sig") as f:
            f.write(HEADER + "\n")
    write(
        f"# процесс: {name} (PID {os.getpid()}); интервал {interval:g} с; "
        f"трассировка {'вкл, отчёт в ' + path + '.trace.txt' if trace else 'выкл'}; "
        f"дочерние процессы {'учитываются' if children else 'не учитываются'}"
    )

    def loop():
        proc.cpu_percent(None)
        prev = None
        while True:
            time.sleep(interval)
            try:
                rss = _rss_mb(proc, children)
                now = time.time()
                if stats["first"] is None:
                    stats["first"] = rss
                    stats["t_first"] = now
                stats["last"] = rss
                stats["t_last"] = now
                stats["peak"] = max(stats["peak"], rss)
                write(
                    f"{datetime.now():%H:%M:%S};{rss:.1f};"
                    f"{proc.cpu_percent(None):.0f};{proc.num_threads()};{_conn_count(proc)}"
                )
                if trace:
                    snap = tracemalloc.take_snapshot().filter_traces(_noise_filters())
                    if tr["base"] is None:
                        tr["base"] = snap
                    else:
                        tr["last"] = snap
                        top = [d for d in snap.compare_to(tr["base"], "lineno") if d.size_diff > 10240][:5]
                        for d in top:
                            write(
                                f"[{datetime.now():%H:%M:%S}] {_place(d.traceback[0])}: "
                                f"+{d.size_diff/1024:.0f} КБ всего, +{d.count_diff} объектов",
                                tpath,
                            )
            except psutil.NoSuchProcess:
                break
            except Exception as e:
                write(f"# ошибка монитора: {e}")

    def finish_trace():
        if not (trace and tr["base"] is not None and tr["last"] is not None):
            return
        write("\n# ИТОГ ТРАССИРОВКИ: топ-3 места по росту памяти за весь замер (внизу вызов, где выделена память)", tpath)
        top = [d for d in tr["last"].compare_to(tr["base"], "traceback") if d.size_diff > 10240][:3]
        for i, d in enumerate(top, 1):
            write(f"{i}. +{d.size_diff/1024:.0f} КБ, +{d.count_diff} объектов", tpath)
            write("\n".join("     " + l for l in d.traceback.format(limit=4)), tpath)

    def finish():
        finish_trace()
        if stats["first"] is None:
            write("# замеров не было: программа проработала меньше одного интервала")
            return
        minutes = (time.time() - t0) / 60
        span = (stats["t_last"] - stats["t_first"]) / 60
        if span >= 1:
            growth = f"{(stats['last'] - stats['first']) / span:+.2f} МБ/мин"
        else:
            growth = "не считается (замер короче минуты)"
        write(
            f"# ИТОГ: первый замер {stats['first']:.1f} МБ; пик {stats['peak']:.1f} МБ; "
            f"последний {stats['last']:.1f} МБ; рост {growth}; "
            f"работала {minutes:.1f} мин"
        )

    threading.Thread(target=loop, daemon=True, name="memmon").start()
    atexit.register(finish)
