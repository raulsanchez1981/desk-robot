"""Copia el dibujo de caras (FaceKit) de server/brain/dashboard.html a virtual_robot/ui/facekit.js.

FaceKit es la copia en JS que Casey mantiene del dibujo del firmware (firmware/src/face.cpp), así que el robot virtual
pinta las mismas caras, píxel a píxel, que la pantalla del robot. Después de traer cambios de upstream:

    python desktop/tools/sync_facekit.py

tests/test_facekit_sync.py falla si la copia ya no coincide con el dashboard.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "server" / "brain" / "dashboard.html"
TARGET = ROOT / "desktop" / "virtual_robot" / "ui" / "facekit.js"
START = "const FaceKit = (() => {"
END = "})();"


def extract(html: str) -> str:
    """El bloque `const FaceKit = (() => { ... })();` tal cual está en el dashboard."""
    start = html.find(START)
    if start < 0:
        raise ValueError(f"no encuentro {START!r} en dashboard.html: ¿ha cambiado de estructura?")
    end = html.find(END, start)
    if end < 0:
        raise ValueError("FaceKit no termina con '})();' en dashboard.html")
    return html[start:end + len(END)] + "\n"


def render(block: str) -> str:
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
    return (f"// GENERADO por desktop/tools/sync_facekit.py desde server/brain/dashboard.html (sha256 {digest}).\n"
            "// No editar a mano: vuelve a ejecutar el script tras actualizar desde upstream.\n" + block)


def expected() -> str:
    return render(extract(DASHBOARD.read_text(encoding="utf-8")))


def main() -> int:
    text = expected()
    if TARGET.is_file() and TARGET.read_text(encoding="utf-8") == text:
        print("facekit.js ya está al día")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"facekit.js actualizado ({len(text.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
