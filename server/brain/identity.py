"""Identidad: reconocer a la familia (personas y gatos) por la cámara, en este PC.

  Personas: YuNet (ya lo usa tracker.py) encuentra las caras y SFace (OpenCV Zoo, Apache-2.0) saca de cada una una
            huella de 128 números; se compara por coseno con las muestras de cada persona dada de alta.
  Gatos:    el detector de objetos de MediaPipe (EfficientDet-Lite0, clase "cat") los encuentra y el ImageEmbedder
            de MediaPipe (MobileNetV3) saca una huella visual del recorte. Distingue gatos que se ven distintos
            (color, manchas); dos gatos casi iguales se confundirán.

El alta la pide el modelo con la herramienta `remember_face` ("Rocky, recuerda mi cara, soy Raúl"): se toman las
muestras de los últimos segundos y las de los siguientes ENROLL_SECONDS. `forget_face` borra una persona, un gato o
todo. Cada pregunta lleva una nota con quién se ve ahora (describe) y los recuerdos privados de alguien solo entran
en el prompt cuando esa persona está delante (memory.audience).

Las huellas son datos biométricos: se guardan en server/identity/identity.json (git-ignored), nunca salen de este
PC (al modelo solo le llegan los nombres) y se borran con `forget_face` o con `faces forget all` en la consola.
Mientras duerme no mira (como la percepción, que solo mira manos). Los modelos se descargan una vez, fijados y
comprobados con SHA-256; si algo falla, se apaga sola y el robot sigue sin ella.

    {"version": 1, "people": {"Raúl": [[0.01, ...], ...]}, "cats": {"Luna": [[...], ...]}}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import config
from .memory import _norm
from .perception import MODELS, ensure_models

PATH = Path(__file__).resolve().parent.parent / "identity" / "identity.json"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"   # en git (tracker.py)
DOWNLOADS = {  # file: (url, sha256)
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
    "efficientdet_lite0.tflite": (
        "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite",
        "4b59100025bea1235a84c1038879a6cccc9f6c49f5e41144e91e74d99e780993"),
    "mobilenet_v3_small.tflite": (
        "https://storage.googleapis.com/mediapipe-models/image_embedder/mobilenet_v3_small/float32/1/mobilenet_v3_small.tflite",
        "bbbb4c51a55a53905af1daec995ca1aae355046f8839bb8c9f5ce9271394bc40"),
}
KINDS = ("person", "cat")
PERSON_MATCH = 0.363   # coseno de referencia de SFace para "misma persona"
CAT_MATCH = 0.80       # los gatos se parecen todos bastante: hace falta un parecido alto...
CAT_MARGIN = 0.02      # ...y que gane claramente al segundo gato
MIN_FACE_PX = 48       # caras más pequeñas dan huellas malas
FACES_EVERY = 1.0      # s entre miradas a las caras
CATS_EVERY = 1.0       # s entre miradas a los gatos (~30 ms cada una)
RECENT = 4.0           # s que un avistamiento cuenta como "ahora"
ENROLL_SECONDS = 5.0
SAMPLE_SPACING = 0.4   # s entre muestras de un alta
MAX_SAMPLES = 15       # por nombre; se quedan las más nuevas
MAX_NAMES = 20


# ── huellas y comparación (puro, sin modelos) ──
def unit(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def best_match(vec: np.ndarray, gallery: dict[str, list]) -> tuple[str | None, float, float]:
    """El nombre más parecido, su parecido (coseno, la mejor de sus muestras) y el del segundo nombre."""
    scores = sorted(((float(np.max(np.asarray(s, dtype=np.float32) @ vec)), name)
                     for name, s in gallery.items() if s), reverse=True)
    if not scores:
        return None, 0.0, 0.0
    return scores[0][1], scores[0][0], scores[1][0] if len(scores) > 1 else 0.0


def recognize(vec: np.ndarray, gallery: dict[str, list], kind: str) -> str | None:
    name, score, second = best_match(vec, gallery)
    if kind == "person":
        return name if score >= PERSON_MATCH else None
    return name if score >= CAT_MATCH and score - second >= CAT_MARGIN else None


def _clean_name(value) -> str:
    return " ".join(str(value or "").split())[:40].strip(" .,!?¿¡")


def load(path: Path | None = None) -> dict:
    path = path or PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("people"), dict) and isinstance(data.get("cats"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "people": {}, "cats": {}}


def _save(data: dict, path: Path | None = None) -> None:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".identity-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _group(kind: str) -> str:
    return "people" if kind == "person" else "cats"


class Identity:
    def __init__(self, eyes, path: Path | None = None) -> None:
        self.eyes = eyes
        self.path = path or PATH
        self.awake: Callable[[], bool] = lambda: True    # main.py: dormido no mira
        self.paused: Callable[[], bool] = lambda: False  # main.py: mientras transcribe o se mueve
        self.enabled = True
        self.ready = False
        self.error = ""
        self._lock = threading.Lock()
        self.data = load(self.path)
        self._seen: dict[tuple[str, str], tuple[float, float]] = {}   # (kind, name) -> (cuándo, tamaño en el cuadro)
        self._unknown: dict[str, deque] = {k: deque(maxlen=10) for k in KINDS}   # (cuándo, cuántos sin reconocer)
        self._recent: dict[str, deque] = {k: deque(maxlen=12) for k in KINDS}    # (cuándo, huella) del más grande
        self._enrolling: dict | None = None   # {"kind", "name", "until", "samples": [...], "last"}
        self._frame_at = 0.0

    def start(self) -> None:
        threading.Thread(target=self._run, name="identity", daemon=True).start()

    # ── modelos y bucle ──
    def _load(self) -> None:
        import cv2
        from mediapipe.tasks.python import BaseOptions, vision
        self._det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), score_threshold=0.7)
        self._rec = cv2.FaceRecognizerSF.create(str(MODELS / "face_recognition_sface_2021dec.onnx"), "")
        self._objects = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(MODELS / "efficientdet_lite0.tflite")),
            score_threshold=0.35, max_results=4, category_allowlist=["cat"]))
        self._embedder = vision.ImageEmbedder.create_from_options(vision.ImageEmbedderOptions(
            base_options=BaseOptions(model_asset_path=str(MODELS / "mobilenet_v3_small.tflite")), l2_normalize=True))

    def _run(self) -> None:
        try:
            ensure_models(DOWNLOADS)
            self._load()
            self.ready = True
            print(f"identity: on ({self._known_line() or 'nobody enrolled yet'})")
        except Exception as e:  # sin red la primera vez, paquete que falta, fichero malo: seguir sin ella
            self.error = str(e)
            print(f"identity: off ({e})")
            return
        import cv2
        seq, faces_at, cats_at, warned = -1, 0.0, 0.0, False
        while True:
            seq = self.eyes.wait_for_new(seq, timeout=1.0)
            now = time.time()
            enrolling = self._enrolling is not None
            if not self.enabled or not self.eyes.jpeg or self.paused() or not (self.awake() or enrolling):
                continue
            # durante un alta, mirar más a menudo lo que se está dando de alta
            every_face = SAMPLE_SPACING if enrolling and self._enrolling["kind"] == "person" else FACES_EVERY
            every_cat = SAMPLE_SPACING if enrolling and self._enrolling["kind"] == "cat" else CATS_EVERY
            do_faces, do_cats = now >= faces_at, now >= cats_at
            if not (do_faces or do_cats):
                self._finish_enrolment(now)
                continue
            img = cv2.imdecode(np.frombuffer(self.eyes.jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            self._frame_at = self.eyes.frame_at
            try:
                if do_faces:
                    faces_at = now + every_face
                    self._look_faces(img, now)
                if do_cats:
                    cats_at = now + every_cat
                    self._look_cats(img, now, cv2)
            except Exception as e:
                if not warned:
                    print(f"identity: a frame failed ({e})")
                    warned = True
            self._finish_enrolment(now)

    def _look_faces(self, img, now: float) -> None:
        h, w = img.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(img)
        rows = sorted((f for f in (faces if faces is not None else []) if f[2] >= MIN_FACE_PX),
                      key=lambda f: -f[2] * f[3])[:4]
        vecs = [(unit(self._rec.feature(self._rec.alignCrop(img, f))), float(f[2] * f[3]) / (w * h)) for f in rows]
        self._sighting("person", vecs, now)

    def _look_cats(self, img, now: float, cv2) -> None:
        import mediapipe as mp
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        found = self._objects.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).detections
        vecs = []
        for d in sorted(found, key=lambda d: -d.bounding_box.width * d.bounding_box.height):
            b = d.bounding_box
            pad = int(0.1 * max(b.width, b.height))   # un poco de margen: orejas y cola
            x0, y0 = max(0, b.origin_x - pad), max(0, b.origin_y - pad)
            x1, y1 = min(w, b.origin_x + b.width + pad), min(h, b.origin_y + b.height + pad)
            if x1 - x0 < 32 or y1 - y0 < 32:
                continue
            crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
            emb = self._embedder.embed(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)).embeddings[0]
            vecs.append((unit(emb.embedding), (b.width * b.height) / (w * h)))
        self._sighting("cat", vecs, now)

    def _sighting(self, kind: str, vecs: list[tuple[np.ndarray, float]], now: float) -> None:
        """Lo visto en un cuadro: quién es cada uno y, durante un alta, una muestra más del más grande."""
        with self._lock:
            gallery = self.data[_group(kind)]
            unknown = 0
            for vec, size in vecs:
                name = recognize(vec, gallery, kind)
                if name is None:
                    unknown += 1
                else:
                    self._seen[(kind, name)] = (now, size)
            self._unknown[kind].append((now, unknown))
            if vecs:
                self._recent[kind].append((now, vecs[0][0]))
            e = self._enrolling
            if e and e["kind"] == kind and vecs and now - e["last"] >= SAMPLE_SPACING * 0.8:
                e["samples"].append(vecs[0][0])
                e["last"] = now

    # ── alta y baja ──
    def remember_face(self, args: dict) -> str:
        """La herramienta `remember_face`. Devuelve el texto para el modelo."""
        name = _clean_name(args.get("name"))
        kind = "cat" if str(args.get("kind") or "").lower() in ("cat", "gato", "gata", "pet") else "person"
        what = "face" if kind == "person" else "look"
        if not self.ready:
            return f"You can't learn faces right now ({self.error or 'the recognizer is still starting'})."
        if not name:
            return "Nothing learned: say whose face it is (a name)."
        if not self.eyes.jpeg or time.time() - self.eyes.frame_at > 3:
            return "Nothing learned: your camera has no picture right now."
        now = time.time()
        with self._lock:
            group = self.data[_group(kind)]
            existing = next((n for n in group if _norm(n) == _norm(name)), None)
            if existing is None and len(group) >= MAX_NAMES:
                return f"You already know {MAX_NAMES} {'people' if kind == 'person' else 'cats'}; forget one first."
            recent = [v for t, v in self._recent[kind] if now - t < 3][-3:]
            other = recognize(recent[-1], {n: s for n, s in group.items() if n != existing}, kind) if recent else None
            if other:
                return (f"Nothing learned: that {what} already looks like {other}. If it isn't {other}, they "
                        f"should ask you to forget {other} first.")
            self._enrolling = {"kind": kind, "name": existing or name, "until": now + ENROLL_SECONDS,
                               "samples": recent, "before": len(recent), "last": now}
        print(f"  (identity: learning {name}'s {what})")
        who = "them" if kind == "person" else "the cat"
        return (f"Learning {name}'s {what} for the next few seconds: tell {who} to stay in front of the camera"
                + (", looking at you and turning the head a little." if kind == "person" else ".")
                + " Say it in a few words, in character.")

    def _finish_enrolment(self, now: float) -> None:
        with self._lock:
            e = self._enrolling
            if not e or now < e["until"]:
                return
            self._enrolling = None
            # Las muestras de antes de pedirlo pueden ser de otro (o de otro gato): se quedan solo las que se
            # parecen a la media de las tomadas después.
            after = e["samples"][e["before"]:]
            ref = unit(np.mean(after, axis=0)) if len(after) >= 2 else None
            limit = PERSON_MATCH if e["kind"] == "person" else CAT_MATCH
            samples = [v for v in e["samples"] if ref is not None and float(v @ ref) >= limit]
            group = self.data[_group(e["kind"])]
            other = recognize(ref, {n: s for n, s in group.items() if n != e["name"]}, e["kind"]) \
                if ref is not None else None
            if len(samples) < 2 or other:
                print(f"  (identity: couldn't learn {e['name']}: "
                      + (f"looks like {other})" if other else "nothing clear in view)"))
                return
            old = group.get(e["name"], [])
            group[e["name"]] = (old + [[round(float(x), 5) for x in v] for v in samples])[-MAX_SAMPLES:]
            _save(self.data, self.path)
        print(f"  (identity: learned {e['name']} — {len(group[e['name']])} samples)")

    def forget_face(self, args: dict) -> str:
        """La herramienta `forget_face`: una persona o gato por nombre, o "all"."""
        name = _clean_name(args.get("name"))
        with self._lock:
            if _norm(name) in ("all", "todo", "todos", "todas"):
                gone = [*self.data["people"], *self.data["cats"]]
                self.data = {"version": 1, "people": {}, "cats": {}}
            else:
                gone = []
                for g in ("people", "cats"):
                    for n in [n for n in self.data[g] if _norm(n) == _norm(name)]:
                        del self.data[g][n]
                        gone.append(n)
            if not gone:
                return f"You don't know anyone called {name or '(no name)'} by sight; nothing forgotten."
            self._seen = {k: v for k, v in self._seen.items() if k[1] not in gone}
            _save(self.data, self.path)
        print(f"  (identity: forgot {', '.join(gone)})")
        return f"Forgotten by sight: {', '.join(gone)}. Their memories are kept unless they ask to forget those too."

    # ── lo que lee el cerebro ──
    def who(self) -> dict:
        """Quién se ve ahora: personas (la más grande primero), gatos y cuántos sin reconocer."""
        now = time.time()
        live = self.ready and self.enabled and now - self._frame_at < 3
        with self._lock:
            seen = sorted(((size, kind, name) for (kind, name), (t, size) in self._seen.items() if now - t < RECENT),
                          reverse=True) if live else []
            # un desconocido cuenta si sale en al menos dos miradas (los detectores a veces ven caras o gatos
            # donde no los hay durante un cuadro)
            unknown = {k: (sorted((n for t, n in self._unknown[k] if now - t < RECENT), reverse=True)[1:2] or [0])[0]
                       if live else 0 for k in KINDS}
        return {"live": live, "people": [n for _, k, n in seen if k == "person"],
                "cats": [n for _, k, n in seen if k == "cat"],
                "unknown_people": unknown["person"], "unknown_cats": unknown["cat"]}

    def describe(self) -> str:
        """La nota de cada pregunta, o "" si no hay nada que decir."""
        w = self.who()
        if not w["live"]:
            return ""
        parts = []
        if w["people"]:
            first = w["people"][0] + (" (closest: most likely the one talking to you)" if w["people"][1:] or
                                      w["unknown_people"] else " (most likely the one talking to you)")
            parts.append(", ".join([first, *w["people"][1:]]))
        if w["unknown_people"]:
            n = w["unknown_people"]
            parts.append(("one person" if n == 1 else f"{n} people") + " whose face you don't know")
        parts += [f"the cat {c}" for c in w["cats"]]
        if w["unknown_cats"]:
            parts.append("a cat you don't recognize" if w["unknown_cats"] == 1 else "cats you don't recognize")
        return f"(Who your camera recognizes right now, may be wrong: {'; '.join(parts)}.)" if parts else ""

    def audience(self) -> set[str] | None:
        """Para memory.py: None = no hay nadie dado de alta (no se filtra); si no, los nombres que están delante."""
        if not self.data["people"]:
            return None
        return {_norm(n) for n in self.who()["people"]}

    def _known_line(self) -> str:
        people, cats = list(self.data["people"]), list(self.data["cats"])
        return "; ".join(x for x in (f"people: {', '.join(people)}" if people else "",
                                     f"cats: {', '.join(cats)}" if cats else "") if x)

    def prompt_block(self) -> str:
        known = self._known_line() or "nobody yet"
        return f"""

Recognizing your family (on this computer, by your camera; only names reach you):
- You know by sight: {known}.
- Each question may say who your camera recognizes right now. The closest person is most likely the one talking:
treat what they say as theirs (save their facts with about = their name) and greet them by name only now and then,
not in every answer. It can be wrong; if they say they're someone else, believe them.
- When someone asks you to remember their face or who they are ("remember my face, I'm Ana"), call `remember_face`
with their name; for a cat or other pet in view, with kind "cat". When they ask you to forget a face, `forget_face`.
- Private memories of a person are only shown to you while that person is in front of you: never tell them to
anyone else."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember_face",
            "description": "Learn to recognize someone in front of your camera (a person, or a cat/pet), by name. "
                         "Only when asked to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Their name, e.g. \"Raúl\" or \"Luna\"."},
                    "kind": {"type": "string", "enum": ["person", "cat"], "description": "person (default) or cat."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_face",
            "description": "Stop recognizing someone (person or cat) by sight: delete what you learned of their "
                           "face. \"all\" forgets every face.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Their name, or \"all\"."}},
                "required": ["name"],
            },
        },
    },
]
QUICK = {"remember_face", "forget_face"}
