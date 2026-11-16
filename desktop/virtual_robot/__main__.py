"""Robot virtual para Windows.

    cd desktop
    ..\\server\\.venv\\Scripts\\python -m virtual_robot            # solo la cara
    ..\\server\\.venv\\Scripts\\python -m virtual_robot --debug    # y el panel para forzar caras y movimientos
    ..\\server\\.venv\\Scripts\\python -m virtual_robot --debug --no-brain   # sin conectarse al cerebro
"""

import argparse

from .app import run


def _log_to_file_without_console() -> None:
    """Con pythonw no hay consola (sys.stdout es None): la salida va a %APPDATA%\\desk-robot-virtual\\app.log."""
    import sys
    if sys.stdout is not None:
        return
    from .settings import config_dir
    config_dir().mkdir(parents=True, exist_ok=True)
    log = open(config_dir() / "app.log", "a", encoding="utf-8", buffering=1)   # noqa: SIM115 - vive con el proceso
    sys.stdout = sys.stderr = log


def main() -> None:
    _log_to_file_without_console()
    parser = argparse.ArgumentParser(prog="virtual_robot", description="Robot virtual de escritorio")
    parser.add_argument("--debug", action="store_true", help="abre también el panel de depuración")
    parser.add_argument("--no-brain", action="store_true", help="no conectarse al cerebro (solo la cara)")
    args = parser.parse_args()
    run(debug=args.debug, brain=not args.no_brain)


if __name__ == "__main__":
    main()
