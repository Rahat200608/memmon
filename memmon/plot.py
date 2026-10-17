"""Рисует график по CSV-отчёту memmon.

Использование:
    python -m memmon plot memmon_12345.csv
Результат: PNG-файл рядом с отчётом.
Нужен matplotlib:  pip install matplotlib
"""
import csv
import os
import sys
from datetime import datetime


def _read(path):
    rows, summary = [], ""
    with open(path, encoding="utf-8-sig", newline="") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "ИТОГ" in line:
                    summary = line.lstrip("# ").strip()
                continue
            rows.append(line.split(";"))
    if len(rows) < 2:
        raise ValueError("в файле нет замеров (нужно хотя бы 1 строка данных)")
    return rows[1:], summary  # первая строка - заголовок


def build(path, out=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Для графика нужен matplotlib. Установи: python -m pip install matplotlib")
        sys.exit(1)

    data, summary = _read(path)

    minutes, mem, cpu, threads, conns = [], [], [], [], []
    day_shift, prev = 0.0, None
    t0 = None
    for r in data:
        try:
            t = datetime.strptime(r[0], "%H:%M:%S")
            sec = t.hour * 3600 + t.minute * 60 + t.second
            if prev is not None and sec + day_shift < prev:
                day_shift += 86400  # перешли через полночь
            sec += day_shift
            prev = sec
            if t0 is None:
                t0 = sec
            minutes.append((sec - t0) / 60)
            mem.append(float(r[1]))
            cpu.append(float(r[2]))
            threads.append(float(r[3]))
            c = float(r[4])
            conns.append(c if c >= 0 else float("nan"))
        except (ValueError, IndexError):
            continue  # пропускаем повреждённые строки

    if not mem:
        raise ValueError("не удалось прочитать ни одной строки данных")

    fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
    series = [
        (mem, "Память, МБ", "tab:blue"),
        (cpu, "Процессор, %", "tab:orange"),
        (threads, "Потоки", "tab:green"),
        (conns, "Соединения", "tab:red"),
    ]
    for ax, (y, label, color) in zip(axes, series):
        ax.plot(minutes, y, color=color, linewidth=1.6)
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.3)

    peak_i = max(range(len(mem)), key=mem.__getitem__)
    axes[0].annotate(
        f"пик {mem[peak_i]:.0f} МБ",
        (minutes[peak_i], mem[peak_i]),
        textcoords="offset points", xytext=(-10, 10), ha="right",
        arrowprops=dict(arrowstyle="->"),
    )
    axes[-1].set_xlabel("Минуты от начала замера")
    fig.suptitle(summary or os.path.basename(path), fontsize=10)
    fig.tight_layout()

    out = out or os.path.splitext(path)[0] + ".png"
    fig.savefig(out, dpi=130)
    print(f"График сохранён: {out}")
    return out


def main(argv):
    if not argv:
        print("Использование: python -m memmon plot файл.csv [график.png]")
        sys.exit(1)
    build(argv[0], argv[1] if len(argv) > 1 else None)
