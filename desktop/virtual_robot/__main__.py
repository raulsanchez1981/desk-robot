"""Robot virtual para Windows.

    cd desktop
    ..\\server\\.venv\\Scripts\\python -m virtual_robot            # solo la cara
    ..\\server\\.venv\\Scripts\\python -m virtual_robot --debug    # y el panel para forzar caras y movimientos
    ..\\server\\.venv\\Scripts\\python -m virtual_robot --debug --no-brain   # sin conectarse al cerebro
"""

import argparse

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="virtual_robot", description="Robot virtual de escritorio")
    parser.add_argument("--debug", action="store_true", help="abre también el panel de depuración")
    parser.add_argument("--no-brain", action="store_true", help="no conectarse al cerebro (solo la cara)")
    args = parser.parse_args()
    run(debug=args.debug, brain=not args.no_brain)


if __name__ == "__main__":
    main()
