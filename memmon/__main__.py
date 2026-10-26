import runpy
import sys


def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python -m memmon script.py [аргументы]   - запустить скрипт под замером")
        print("  python -m memmon plot файл.csv           - нарисовать график по отчёту")
        sys.exit(1)

    if sys.argv[1] == "plot":
        from memmon import plot
        plot.main(sys.argv[2:])
        return

    sys.argv = sys.argv[1:]      # сначала подменяем argv, чтобы имя файла отчёта взялось от скрипта
    import memmon
    memmon.start()
    runpy.run_path(sys.argv[0], run_name="__main__")


main()
