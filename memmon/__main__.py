import runpy
import sys

import memmon


def main():
    if len(sys.argv) < 2:
        print("Использование: python -m memmon script.py [аргументы]")
        sys.exit(1)
    memmon.start()
    sys.argv = sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")


main()
