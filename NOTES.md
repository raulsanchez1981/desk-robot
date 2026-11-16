# Robot virtual para Windows — notas de trabajo

Basado en los ficheros del repo en `main` @ `68c98b9` (firmware 0.4.3, brain v2.1). Referencias como
`fichero:línea`. Todo lo marcado **[hipótesis]** está deducido del código y no lo he ejecutado todavía.

---

## FASE 0 — Análisis

### (a) Protocolo firmware ↔ cerebro

**Transporte** (`docs/protocol.md`, `server/brain/main.py:1648`)

- WebSocket plano `ws://<pc>:8765/`, sin TLS. Mensajes de texto = JSON; binarios = 1 byte de tipo + payload.
- Tamaño máximo de mensaje: 1 MB (`max_size`).
- **Origin**: el servidor solo acepta `Origin: file://` o *sin* Origin (`origins=["file://", None]`). Un navegador
  siempre manda el origen de su página → **una página web no puede ser el cliente**. Un cliente Python
  (`websockets`) no manda Origin por defecto → sí vale.
- Keepalive: el firmware hace ping cada 15 s (`link.cpp:37`); el servidor usa los pings por defecto de `websockets`.
  Cualquier cliente `websockets` los contesta solo.

**Autenticación** (`main.py:187-237`)

1. El primer mensaje debe llegar en ≤ 2 s, ser texto JSON ≤ 4 KB y tener `type: "hello"` y `token` = `ROBOT_TOKEN`.
2. `ROBOT_TOKEN` del servidor < 16 caracteres o `change-me` → rechaza a todos (1008).
3. Token incorrecto → espera 1 s (serializado con un lock) y cierra 1008. Sin respuesta.
4. Un robot a la vez. Una segunda conexión con token válido sustituye a la vieja si viene de la misma IP o la vieja
   lleva ≥ 8 s callada; si no, 1013.
5. Máximo 8 conexiones a la vez en fase de saludo.

**Al conectar, el servidor envía** (`main.py:238-248`): `mic` (on si el micro del robot es el que se escucha),
`stream {on, fps: CAMERA_FPS=10, size: "vga"}`, `glance {on:false}`, `settings {...}`, `face {save, pack}`,
`volume`, `asleep`.

**Robot → servidor**

| Mensaje | Formato | Frecuencia / cuándo | Qué hace el cerebro |
| --- | --- | --- | --- |
| `hello` | `{type, who, fw, token, boot?, up_s?, rssi?, ...}` | primero, una vez | auth + línea de log de salud (campos opcionales) |
| `state` | `{type, pan, emotion}` | cada 5 s | **ignorado** (solo actualiza "última vez oído") |
| `temp` | `{type, c}` | cada 10 s | se muestra en el dashboard; opcional |
| `speak_done` | `{type, dry_ms?, wait_ms?, next_ms?, rssi?}` | al terminar de sonar una respuesta | **desmutea el micro**; timeout = duración + 5 s |
| `head_moving` | `{type, on}` | modo "roam" dormido | pausa la detección de saludo. **No está en protocol.md** |
| `0x01` + PCM | 16 kHz mono s16le, 30 ms = 480 muestras = 960 B | continuo mientras `mic on`, **no mientras habla** (`main.cpp:770`) | `ears.push_audio` (se descarta si el payload no es par o si está muteado) |
| `0x02` + JPEG | tamaño/fps del último `stream` | continuo; 8 fps mientras habla (125 ms), 5 fps dormido (200 ms) | `eyes.push_frame`: **rota `CAMERA_ROTATE` (270 por defecto) y espeja (`CAMERA_MIRROR=True`)** |
| `0x03` + JPEG | foto nítida (`snapshot`) | respuesta a `snapshot` | se rota/espeja igual; se usa para preguntas visuales y `look` |

**Servidor → robot**

| Mensaje | Formato | Notas |
| --- | --- | --- |
| `emotion` | `{name}` (12: neutral happy sad angry surprised sleepy thinking curious skeptical excited love confused) | |
| `pan` / `tilt` | `{deg}` | pan −95..95 (+ = derecha del robot), tilt −85..85 (+ = arriba). El firmware suaviza: pan 150°/s, 450°/s²; tilt 160°/s, 600°/s² (`config.h:68-92`) |
| `motion` | `{axis, speed, accel}` | límites de velocidad durante bailes (`dance.py:134`). **No está en protocol.md** |
| `speak_begin` | `{bytes: 0}` | siguen binarios `0x01` de TTS, 3200 B = 100 ms; el servidor va como mucho 2 s por delante del tiempo real |
| `speak_end` | | el robot contesta `speak_done` cuando ha sonado todo |
| `mouth` | `{level}` RMS 0..1, ~25/s; `-1` = fin | solo cuando la voz suena **en el PC** con robot conectado |
| `volume` | `{level}` 0..1 | |
| `asleep` | `{on}` | dormido: cara de sueño 5 s y luego reloj; cabeza al centro |
| `glance` | `{on}` | el servidor siempre manda off |
| `mic` | `{on}` | |
| `stream` | `{on, fps, size: qvga\|vga}` | |
| `snapshot` | `{size: vga\|svga\|xga\|sxga\|uxga}` | por defecto `xga` 1024×768 |
| `settings` | reloj, tiempo, brillo, pantalla en reposo... | para la pantalla de reloj; el robot virtual puede ignorar casi todo |
| `face` | `{save, pack}` | el pack de caras completo (ver b) |

**Flujo de una respuesta hablada con robot conectado** (`main.py:875-951`): `emotion thinking` → (LLM) →
`emotion <x>` → al tener el primer audio: `ears.muted.set()` → `speak_begin` → `0x01`×N → `speak_end` → espera
`speak_done` → `ears.muted.clear()`. El firmware además deja de mandar micro mientras su altavoz suena. Es
exactamente el anti-eco que quieres: **el cerebro no escucha desde el primer audio hasta que el cliente dice
`speak_done`**, así que el cliente decide cuándo se ha apagado de verdad el altavoz (puede añadir cola de reverb).

**Otras cosas relevantes del cerebro**

- `console_loop` lee stdin; **EOF = el cerebro se apaga** (`main.py:1599-1606`). Si lo lanzamos como proceso hijo
  hay que darle un stdin en pipe abierto (lo que hace `launcher.py:111-113`), nunca `pythonw` sin consola.
- API HTTP local en `:8767` (`eyes.py`): `/status` (JSON con emoción, awake, speaking, tracking, pan/tilt...),
  `/frame`, `/stream`, y `POST /api/<acción>` con cabecera `X-Rocky-Console`. Útil para la bandeja (dormir, volumen,
  rotación de cámara) sin tocar `server/`.
- Ajustes persistentes en `server/settings.json` (git-ignored): `rocky.mic`, `rocky.speaker_out`,
  `rocky.camera_rotate`, etc. Se pueden cambiar desde el dashboard o la API sin tocar código.

### (b) Expresiones y "packs de caras"

- **Emociones**: lista fija de 12 en `server/brain/faces.py:36` = `config.EMOTIONS` = `kEmotionNames` en `face.cpp`.
  El LLM etiqueta cada respuesta con una (`thinking.py`), y `SpokenReply._on_emotion` manda `emotion` en cuanto se
  conoce, antes de la voz.
- **Pack** (`faces.py:1-23`, `server/faces/*.json`): JSON con `gap`, `y`, `cyclops`, `outline`, `glint`,
  `mouth` (talk|always|never), `asleep` (ojo cerrado) y `emotions.<nombre>` = forma de ojo (`w h rt rb st sb lid
  cheek dx dy`), `right` opcional para el ojo derecho, `fx` (blush, tear, dots, pop, steam, shake, hearts, question,
  sparkle, bounce, wobble), `gaze`, `pop`, `smile`. Cuatro incluidos (rocky/Default, blocky, bean, visor) y los
  propios en `server/faces/custom/`.
- **Cómo llega**: el cerebro manda el pack completo en `{"type":"face","save":true,"pack":{...}}` al conectar, al
  recargar ajustes y al previsualizar en el editor (`save:false`). La emoción va aparte, por nombre.
- **Quién anima**: el firmware (`face.cpp`, 30 fps, 128×64 monocromo) hace morph entre formas, parpadeo, sacadas,
  pupilas, flourishes, boca con el nivel del altavoz (o con `mouth` si la voz suena en el PC), respiración y Z's al
  dormir. El cerebro solo dice *qué* emoción y *si está dormido*.
- **Dormirse si se le ignora**: lo decide el cerebro (`doze_loop`, `main.py:1476`): pasados `AWAKE_SECONDS` (60 s)
  manda `pan 0`, `tilt 0`, `asleep on`. El robot virtual solo tiene que obedecer.
- **Clave para el robot virtual**: `dashboard.html:~990-1340` tiene una **copia en JS del dibujo del firmware**
  (`class Sim` + `paint()`), píxel a píxel, que lee el mismo JSON del pack. El README dice que se mantiene en sincronía
  con `face.cpp`. Reutilizarla nos da las caras idénticas al robot y cualquier pack nuevo gratis.

### (c) Qué detecta el cerebro con la cámara y cómo

Todo trabaja sobre los JPEG `0x02` que llegan del robot, **después** de rotarlos/espejarlos en `eyes.push_frame`.

| Qué | Dónde | Cómo | Qué hace con ello |
| --- | --- | --- | --- |
| Cara (seguimiento) | `tracker.py` | YuNet ONNX (OpenCV), cara más grande, ~6 ms/frame | Si `tracking` está on ("track me"), mueve pan/tilt hacia la cara. **Supone que la cámara va montada en la cabeza**: posición absoluta = pose de la cabeza cuando se tomó el frame + desvío en el frame (FOV 104°×92°) |
| Cara (atributos) | `perception.py` | MediaPipe face landmarker: sonrisa (`mouthSmile` > 0.45), boca abierta, ojos cerrados, mirando (yaw/pitch < 25°), distancia aprox. | **Solo** una nota de texto junto a la foto en preguntas visuales ("one person about 1 m away, looking at you, smiling") y el panel del dashboard. **La sonrisa no dispara ninguna reacción.** |
| Saludo | `perception.py:145-184` | MediaPipe gesture recognizer: mano abierta cuya muñeca va de lado a lado (> 6 % del ancho en ≥ 4 muestras) | Si está dormido y hay robot conectado: se despierta, cara `surprised`, dice la línea `wake` (`main.py:1066`) |
| Modo concentración | `focus.py` + `decisions.py` | Cada 3 s el frame más reciente va a la **Decisions API de OpenAI** (`OPENAI_API_KEY`, ~3 céntimos/25 min): "¿está usando el móvil?" → probabilidad. ≥ 0.8 tres veces seguidas = te riñe | Gira hacia ti (1.2 s de tracking) y habla. **Exige robot conectado** (`main.py:1375`) |
| Qué hay en la escena | el LLM | Foto del stream con cada pregunta despierto; foto nítida (`snapshot`) si la pregunta es visual | |

Los modelos MediaPipe (~12 MB) se descargan la primera vez con checksum. Mientras habla, transcribe o mueve la cabeza
por lenguaje corporal, la percepción se pausa.

### (d) Trivial vs difícil para el robot virtual

**Trivial**

- Conectarse y autenticarse: un `hello` con el token leído de `server/.env` (sin imprimirlo).
- Obedecer `emotion`, `asleep`, `face`, `volume`, `glance`, `settings`: estado que se pasa a la vista.
- Dibujar las caras: reutilizar el `Sim` JS del dashboard.
- Dormirse si se le ignora: ya lo decide el cerebro.
- Mandar `state` cada 5 s (y opcionalmente `temp`, que podemos omitir).
- Micro del PC → frames `0x01` de 960 B cada 30 ms.

**Medio**

- **Simular el cuello**: copiar el perfil de movimiento del firmware (velocidad + aceleración; ya existe en Python
  en `tracker.Motion`) para que giros y bailes se vean como en el robot, y dibujar pan/tilt como una transformación
  2D/3D de la cabeza.
- **Reproducir el audio TTS**: buffer de reproducción con 200 ms de colchón, nivel RMS para la boca, `speak_done`
  cuando el dispositivo de salida haya vaciado de verdad (más ~150 ms de cola por la reverb de la sala).
- **Anti-eco**: no mandar micro mientras suena + ese margen. El cerebro ya mutea hasta `speak_done`.
- **Cámara**: webcam con OpenCV, JPEG a 640×480 a 10 fps, `snapshot` a 1024×768 (o lo que dé la webcam). Ajustar la
  orientación: poner `camera_rotate = 0` en `settings.json` (vía API/dashboard) y **espejar el frame antes de
  enviarlo**, porque `CAMERA_MIRROR=True` está fijo en `config.py` y deshace el espejo del sensor del robot.
- Interruptores de cámara/micro: dejar de mandar frames. El cerebro lo tolera (sin frame = "no puede ver").

**Difícil**

- **Seguimiento de cara con una webcam fija.** El tracker cierra el lazo asumiendo que la cámara gira con la
  cabeza. Con una webcam fija, al girar la cabeza virtual la cara no se mueve en la imagen → el tracker sigue
  empujando hasta el tope (realimentación positiva). Sin tocar `server/` la solución es una **cámara pan-tilt
  virtual**: el cliente desplaza la imagen de la webcam en sentido contrario a la pose de su cabeza
  (`px_por_grado = ancho / 104`) y rellena con negro lo que queda fuera. Así el lazo es estable y la cabeza acaba
  "mirándote". Coste: con la cabeza girada, el LLM y la percepción ven un marco con bordes negros, y "mira a la
  puerta" mostrará sobre todo negro (lo cual es honesto: la webcam no ve ahí). Hay que medir el FOV real de tu
  webcam para que los ángulos cuadren.
- **Windows como plataforma del cerebro** (fase 1), ver abajo.
- **Ventana transparente siempre encima** con WebView2: depende de la librería (ver propuesta de UI).

**Riesgos de Windows vistos en el código [hipótesis, se verifican en fase 1]**

1. Voz de reserva (`mouth.py:438-455`): se lanza `powershell -Command <script> <ruta>`. Con `-Command`, PowerShell
   concatena los argumentos sobrantes al propio script, así que `$args[0]` probablemente llega vacío y
   `SetOutputToWaveFile` falla. Además `[Console]::In` usa la página de códigos de la consola, no UTF-8.
2. Reproducción (`mouth.py:542-544`): `sounddevice.play` a 16 kHz con el `InputStream` del micro abierto. El autor
   lo marca como no probado; `sd.play` usa un stream global y la tasa de 16 kHz puede no aceptarse en WASAPI.
3. `config.py:11` lee `.env` con `read_text()` sin `encoding` → cp1252 en Windows. Igual `characters.py:128`.
4. Salida por consola: `print` con "—", "→" cuando stdout va a un pipe (launcher) → posible `UnicodeEncodeError`.
   Se arregla sin tocar código con `PYTHONIOENCODING=utf-8`.
5. Wheels para Python 3.13 en Windows de `mediapipe==1.1.0`, `onnxruntime==1.29.0`, `faster-whisper` (ctranslate2).
6. Control del ordenador: apps/música/volumen/Shortcuts son solo Mac; búsquedas y webs sí funcionan.

---

## Propuesta de arquitectura

### Cliente virtual: viable sin tocar `server/`

El protocolo no lo impide: un cliente Python que hable WebSocket, mande el `hello` con el token y se comporte como
el firmware es indistinguible de la placa. Todas las funciones pedidas (cara, cuello, voz, micro, webcam,
seguimiento, sonrisa, saludo, concentración) llegan por el protocolo existente. Lo único que no se puede hacer
"desde fuera" de forma limpia son los arreglos de Windows de la fase 1.

```
┌──────────────── desktop/  (nuevo, nuestro) ─────────────────┐
│  proceso "robot virtual" (Python 3.13)                      │
│   link.py    WebSocket ↔ cerebro, hello + token, state 5 s  │
│   audio.py   micro → 0x01 · 0x01 TTS → altavoz, speak_done  │
│   camera.py  webcam → 0x02 / 0x03, cámara pan-tilt virtual  │
│   neck.py    perfil de movimiento del firmware (pan/tilt)   │
│   tray.py    bandeja, atajos, mute micro/cámara, dormir     │
│   ui/        ventana: cara (Sim JS copiado) + depuración    │
└───────────────────────┬─────────────────────────────────────┘
                        │ ws://127.0.0.1:8765 (mismo protocolo que la placa)
┌───────────────────────┴─────────────────────────────────────┐
│  server/  (de Casey, sin cambios)  python -m brain.main     │
└─────────────────────────────────────────────────────────────┘
```

- **Quién hace el audio**: el cliente (camino "robot"), no el cerebro. Así controlamos la reproducción en Windows,
  la boca va sincronizada con lo que realmente suena y el anti-eco depende de nosotros (`speak_done` tardío + no
  mandar micro mientras suena). Alternativa más simple pero peor: `speaker_out=computer` y `mic=computer` en
  ajustes, y el cliente solo dibuja (usa `mouth`); pero depende de la reproducción no probada del cerebro en Windows.
- **Arreglos de Windows en el cerebro sin editar `server/`**: un lanzador `desktop/run_brain.py` que importa
  `brain`, sustituye `mouth._synthesize_builtin` y `mouth.play` por versiones que funcionan en Windows y arranca
  `brain.main.main()`. Sigue pudiendo hacer `git pull` de Casey sin conflictos. Coste: si Casey renombra esas
  funciones, el parche falla (lo detectamos al arrancar con una comprobación explícita). Complemento opcional:
  mandar los arreglos a Casey como PR para que desaparezca el parche.
- **Personaje intercambiable**: el cliente no sabe nada de Rocky. Nombre, voz, wake word y personalidad siguen en
  `personality.py` / `server/characters/` / pestaña Personalities del dashboard; la cara llega en el mensaje `face`.
  El único "Rocky" en el cliente será el texto por defecto del título, sacado de `/status` o de configuración.
- **Secretos**: el cliente lee `ROBOT_TOKEN` de `server/.env`; nunca se imprime ni va a logs (los logs del cliente
  pasan por un filtro que enmascara el token y cualquier `*_KEY`). Nada nuevo se guarda en el repo.
- **Configuración del cliente** (posición de la ventana, atajos, FOV de la webcam, dispositivo de cámara) en
  `%APPDATA%\desk-robot-virtual\config.json`, fuera del repo.

### Interfaz: dos opciones

**A. pywebview (WebView2 de Edge) + Python** — *recomendada*

- La ventana es HTML/canvas; la cara es el `Sim` + `paint()` copiados de `dashboard.html` (MIT, misma fuente que
  usa el autor para su preview). Sincronizar con Casey = recopiar ese bloque; podemos dejar un script que lo extraiga
  entre marcadores y avise si cambió.
- Python hace todo lo demás (WebSocket, audio, webcam) y empuja el estado a la página con `evaluate_js` o una API
  expuesta. La página nunca habla con el cerebro (no podría: Origin).
- Pros: caras idénticas al robot sin reescribir nada; panel de depuración trivial en HTML; todo el código "difícil"
  en Python; dependencia pequeña (WebView2 ya viene con Windows 11).
- Contras: dos lenguajes (algo de JS); la transparencia real del fondo en Windows con pywebview es el punto débil
  (soporte `transparent` en WebView2 limitado según versión) → lo verifico con un spike de 30 min al empezar la
  fase 2; plan B: ventana sin bordes con forma/color de fondo de la "pantalla OLED", que visualmente encaja.
  Bandeja con `pystray` en otro hilo y atajos globales con `RegisterHotKey` (vía `pynput` o `ctypes`).

**B. PySide6 (Qt)**

- Pros: todo Python; ventana sin bordes, siempre encima y translúcida es nativa y fiable
  (`WA_TranslucentBackground`); `QSystemTrayIcon` incluido; un solo bucle de eventos.
- Contras: hay que **portar el dibujo de caras** (~350 líneas de JS / ~700 de C++) a Python/QPainter y mantenerlo a
  mano cada vez que Casey toque `face.cpp`; Qt es grande (≈ 150 MB instalado) y su modelo de hilos + asyncio
  (qasync) añade fricción; LGPL.

**Recomendación: A.** Para un backend, lo más cómodo de mantener es no tener un segundo dibujante de caras que
divergirá del original; el JS que se toca es poco y está aislado. Si el spike de transparencia falla y la ventana
"tipo OLED" no te convence, cambio a B antes de escribir el resto (la lógica de `desktop/` en Python no cambia).

### Estructura propuesta

```
desktop/
  requirements.txt       pywebview, pystray, Pillow, (opencv/sounddevice/websockets ya vienen del cerebro)
  run_brain.py           cerebro + parches de Windows
  virtual_robot/         link, audio, camera, neck, tray, config, ui/
  tests/                 unittest, sin hardware
```

Un solo venv (`server/.venv`, Python 3.13) con `desktop/requirements.txt` encima, para no duplicar
OpenCV/numpy. El robot virtual será un proceso aparte del cerebro (como la placa); en la fase 4 puede lanzar el
cerebro como hijo con stdin en pipe.

### Decisiones tomadas (2026-11-16)

- **Seguimiento de cara: aplazado.** De momento la webcam sirve para saber si estás o no. El cerebro ya lo
  calcula en `perception.summary()` (`people`, `face`, expuesto en `/status` → `notices`). Sin seguimiento no hace
  falta la cámara pan-tilt virtual; queda apuntada para más adelante.
- **UI: pywebview.** Ventana cuadrada, sin bordes, siempre encima, redimensionable y movible. La transparencia deja
  de ser imprescindible: el fondo será el de la "pantalla" del robot.
- **Repo propio (fork)**: `origin` = fork del usuario, `upstream` = `cgro00/desk-robot`; actualizar con
  `git fetch upstream && git merge upstream/main`. Como los cambios ya no van al repo de Casey, los arreglos de
  Windows se hacen **directamente en `server/`**, en commits pequeños y localizados (menos frágil que parchear en
  caliente con `run_brain.py`; los conflictos al hacer merge serán raros y pequeños). El código nuevo sigue en
  `desktop/`.

### Decisiones pendientes (Fase 0, ya resueltas arriba salvo commits)

1. **¿OK a la arquitectura de cliente virtual + `run_brain.py` con parches** (en vez de editar `server/`)?
2. **UI: ¿A (pywebview) o B (Qt)?**
3. **Seguimiento de cara con webcam fija: ¿OK a la "cámara pan-tilt virtual"** (desplazar la imagen según la cabeza,
   con bordes negros) o prefieres que el seguimiento solo mueva la cabeza virtual sin cerrar el lazo (requeriría
   tocar `tracker.py`)?
4. **Commits**: tu CLAUDE.md dice no commitear sin confirmación explícita y el encargo pide commits pequeños.
   ¿Me autorizas a commitear en `feat/robot-virtual-windows` al cerrar cada paso de fase sin preguntar cada vez?
   (Nunca a `main`, nunca push.)

---

## FASE 1 — Cerebro en Windows con micro y altavoz del PC

Entorno: Windows 11 Pro, Python 3.13.17 (winget, junto al 3.12 existente), venv en `server/.venv`.

**Comprobado de verdad**

- `pip install -r requirements.txt`: todas las versiones fijadas tienen wheel para cp313/win_amd64 (mediapipe 1.1.0,
  onnxruntime 1.29.0, ctranslate2 4.9.0, opencv-contrib 5.0).
- Tests del proyecto: 119/119 OK (`python -m unittest discover -s tests -p "test_*.py"`; en PowerShell el
  `tests/test_*.py` del README no funciona porque no expande comodines).
- Arranque completo sin robot con stdin/stdout en pipe: arranca en ~2 s una vez descargados los modelos, carga
  MediaPipe, abre el micro por defecto (auriculares A50, MME), `say` sintetiza y reproduce sin errores, `quit`
  cierra limpio.
- Reproducción con `sounddevice` a 16 kHz con el `InputStream` del micro abierto: sin errores y con la duración
  correcta (MME re-muestrea). No es necesario el truco de `afplay` del Mac.

**Problemas y arreglos (commits en la rama)**

1. Voz de reserva: `powershell -Command <script> <ruta>` pega los argumentos al script, `$args[0]` llegaba vacío y
   `SetOutputToWaveFile` fallaba ("'path' no puede ser una cadena vacía"). Ahora la ruta va en
   `DESK_ROBOT_TTS_OUT`, stdin en UTF-8, `$ErrorActionPreference='Stop'` y sin ventana de consola.
2. Codificación: `.env`, `settings.json`, packs, personajes, el `.txt` de depuración y el `dashboard.html` se leían
   o escribían con cp1252. Ahora UTF-8 explícito (`utf-8-sig` para `.env`, por si Notepad le pone BOM).
3. Salida del cerebro por pipe: sin `PYTHONIOENCODING` sale en cp1252 y "—" llega como basura al lector UTF-8 (no
   se cae, porque esos caracteres existen en cp1252). El launcher ahora fija `PYTHONIOENCODING=utf-8` y lee en
   UTF-8. Cualquier proceso nuestro que lance el cerebro debe hacer lo mismo.

- Conversación con Claude Haiku 5.5 **directo en Anthropic** (`LLM_BASE_URL=https://api.anthropic.com/v1/`,
  `LLM_MODEL=claude-haiku-5-5`) por el endpoint compatible con OpenAI: respuesta en personaje, etiqueta de emoción
  (`excited`, `happy`), recorte a 3 frases y llamada a herramienta (`look` izquierda → pan −40°). Primer audio a
  1,2-1,8 s del final de la pregunta con la voz de Windows.

**No probado todavía**

- Voz de Fish Audio (sin `FISH_AUDIO_API_KEY`).
- Palabra de activación y transcripción con tu voz (requiere que hables tú).
- Que el audio se oiga bien: yo no puedo oírlo; la duración de la reproducción cuadra.
- El launcher (`launcher.py`, dashboard en :8766) en Windows.

### Modo español (`ROBOT_LANGUAGE=es` en `server/.env`)

Todo lo específico del idioma está en `server/brain/language.py`; en los ficheros de Casey solo hay enganches
pequeños (`config.py` al final, `ears.py` idioma de Whisper + `normalize` sin tildes, `mouth.py` voz por idioma,
`personality.py` reglas añadidas al prompt). Con `ROBOT_LANGUAGE` vacío o `en` todo se comporta como el original.

- Reconocimiento: `faster-whisper` **small** multilingüe con `language="es"` (base.en solo entiende inglés),
  revisión fijada `536b0662…`. ~480 MB la primera vez. Si va lento, `base` (ver `language.py`).
- Activación: "oye / hola / hey / ey Rocky" (y variantes "Roki", "Roqui"…); como en inglés, el nombre solo no
  basta.
- Frases sin modelo en español, **sumadas** a las inglesas: dormir ("buenas noches", "Rocky, a dormir"), seguir
  ("sígueme", "deja de seguirme"), concentración ("para la concentración") y preguntas visuales ("¿qué ves?",
  "mira esto"…). Se comparan sin tildes.
- Voz de reserva de Windows elegida por idioma: es-ES → Helena, en-US → Zira (antes usaba la predeterminada del
  sistema, Helena, también para el inglés).
- Personalidad: se añade al prompt "contesta siempre en español de España" y, para Rocky, sus muletillas en español
  ("Pregunta:", "¡Asombroso!", "¡Choca mi puño!") con ejemplos y las cuatro líneas fijas traducidas. Editables en
  `language.py`. Un personaje del dashboard recibe solo la regla de idioma (sus líneas fijas son las suyas).
- Probado: 125 tests OK con `ROBOT_LANGUAGE=en` y `=es`; `ask ¿qué es un fin de semana?` → respuesta en español en
  personaje; `ask gira la cabeza a la izquierda` → `look` izquierda. Primer audio a 1,2-1,8 s.
- Pendiente: probarlo hablando (tú). Los mensajes de consola del cerebro siguen en inglés ("say hey Rocky").

---

## FASE 2 — Ventana flotante con la cara y panel de depuración (sin cerebro)

Arranque (desde `desktop/`, con el venv del cerebro):

    ..\server\.venv\Scripts\python -m pip install -r requirements.txt   # una vez
    ..\server\.venv\Scripts\python -m virtual_robot --debug

**Cómo está hecho**

- `virtual_robot/ui/facekit.js`: copia **generada** del dibujo de caras del dashboard (`tools/sync_facekit.py`),
  que a su vez es la copia del firmware. Tras un `git merge upstream/main`, volver a ejecutar el script; el test
  `test_copy_matches_dashboard` falla si se olvida.
- `ui/robot.js`: `robot.handle(msg)` acepta los mensajes del protocolo (`emotion`, `pan`, `tilt`, `motion`,
  `asleep`, `face`, `mouth`, `settings`…). Cuello con el mismo perfil de velocidad/aceleración que los servos;
  boca con el nivel RMS y caducidad de 300 ms como el firmware; dormido: cara de sueño 5 s y luego reloj.
- `app.py`: ventana sin bordes, siempre encima, arrastrable desde cualquier punto y redimensionable desde el asa
  de la esquina (160-1400 px de ancho). **La ventana es solo la pantalla**: negra, 2:1 como el OLED de 128×64,
  rasgos en blanco (pintados con nuestros colores en `robot.js`; FaceKit sigue sin tocar). Sin carcasa, el giro de
  cabeza se ve como la cara desplazándose y girando en perspectiva dentro de la pantalla. Posición y tamaño en `%APPDATA%\desk-robot-virtual\config.json`; si la
  posición guardada no cabe entera en ningún monitor, vuelve abajo a la derecha del principal.
- Panel de depuración (`--debug`): las 12 emociones, dormir/despertar, hablar simulado, recorrer caras, pan/tilt,
  movimientos (centro, mirar a los lados, asentir, negar, bailar) y selector de pack.

**Decisiones / hallazgos**

- **Sin fondo transparente**: pywebview 6.2.1 + WebView2 157 en Windows pinta un fondo opaco aunque se pida
  `transparent=True` (probado con captura). En su lugar la ventana es la pantalla negra, con las esquinas
  redondeadas nativas de Windows 11 (DWM).
- pywebview descuenta un borde (16×39 px) que una ventana sin marco no tiene: el tamaño y la posición se fijan con
  `SetWindowPos` directamente.

**Probado de verdad** (script con capturas): tamaño exacto 260→180 px, emociones (`happy`, `love`), cabeza a
pan 60 / tilt 20, boca hablando, dormir → reloj a los 5 s, posición guardada. 9 tests de `desktop/` OK.

**No probado por mí**: arrastrar con el ratón y redimensionar desde el asa (necesitan tu mano); el panel de
depuración solo lo he abierto, no clicado.

---

## FASE 3 — La ventana conectada al cerebro como robot virtual

Arranque: el cerebro como siempre (`python -m brain.main` o el launcher) y, aparte,
`..\server\.venv\Scripts\python -m virtual_robot [--debug]` desde `desktop/`. Si el cerebro no está, la cara se
duerme (reloj) y reintenta cada 3 s, como la placa.

**Cómo está hecho** (`virtual_robot/link.py`, `audio.py`)

- Cliente WebSocket a `ws://127.0.0.1:8765` con `hello` (`who: virtual-robot`, `fw: virtual-0.1.0`, token de
  `server/.env`, nunca impreso). Sin cabecera Origin, que es lo que el servidor exige. Sin tocar `server/` para
  esto: el cerebro lo trata como a la placa (micro del robot, voz por el robot, `speak_done`).
- Mensajes de cara (`emotion`, `pan`, `tilt`, `asleep`, `face`, `motion`, `settings`…) → `robot.handle()`. Los que
  llegan antes de que cargue la ventana se encolan y se entregan en orden.
- Voz: frames `0x01` a un buffer; empieza con 200 ms de colchón; boca con el RMS de lo que suena, retrasado la
  latencia del dispositivo (200 ms con MME); `speak_done` cuando ha salido todo + latencia.
- Micro: 30 ms / 480 muestras a 16 kHz, solo si el cerebro lo pide (`mic on`). **Anti-eco**: cortado mientras
  suena la voz y 0,35 s después; el cerebro además no escucha hasta `speak_done`.
- `state` cada 5 s. `stream`/`snapshot` se ignoran hasta la fase 5 (una pregunta visual espera ~1 s la foto que no
  llega y sigue sin imagen).
- Cambio en `server/brain/thinking.py`: sin foto de contexto, se le dice al modelo que no ve nada (antes, sin
  webcam, decía que veía bien).

**Fallo encontrado y arreglado**: al vaciarse el buffer, el callback de audio "rearrancaba" la reproducción en cada
bloque y `speak_done` nunca salía (el cerebro esperaba su timeout). Ahora cada respuesta arranca una vez; test de
regresión en `tests/test_link_audio.py`.

**Probado de verdad** (cerebro real + ventana, pregunta por consola): "robot connected! (fw virtual-0.1.0…)", el
cerebro escucha por el "robot mic", respuesta en español, la voz suena por el altavoz del PC, boca moviéndose,
micro cortado todo el rato que sonó, `speak_done` a tiempo (sin "robot never said it finished speaking"), y al
cerrar el cerebro la cara se duerme. 15 tests de `desktop/` y 125 del cerebro OK.

**No probado por mí**: una conversación por voz con la ventana (necesita que hables), el eco con altavoces en vez
de auriculares.

---

## FASE 6 (nueva) — Rediseño de la interfaz

Pedida el 2026-11-16, para cuando todo funcione: caras de más resolución (ahora son los 128×64 píxeles del OLED
escalados, se ven pixeladas), otros personajes y animaciones. Punto de partida: `robot.handle(msg)` ya separa el
protocolo del dibujo, así que un renderizador nuevo solo tiene que implementar emociones, cuello, boca y sueño.

---

## FASE 4 — Bandeja, atajos, dormir, arranque del cerebro y con Windows

Arranque normal (ya no hacen falta dos terminales): desde `desktop/`,
`..\server\.venv\Scripts\python -m virtual_robot` (o doble clic en `desktop\run_virtual_robot.pyw` con el
`pythonw` del venv). La app arranca el cerebro; si ya hay uno escuchando en 8765 (terminal, launcher) usa ese.

**Qué hay**

- `brain_process.py`: cerebro como hijo (stdin en pipe, sin ventana, `PYTHONIOENCODING=utf-8`), salida en
  `%APPDATA%\desk-robot-virtual\brain.log` con claves/tokens enmascarados (`sk-…`, hex largos, `*KEY=`, `*TOKEN=`).
  Se cierra con su propio `quit` al salir. Avisa si el puerto 8767 lo tiene otro proceso (cerebro colgado).
- `tray.py`: icono (ojos blancos sobre negro, punto rojo si micro o cámara apagados) con menú: mostrar la cara,
  micro, cámara, dormir/despertar, panel de depuración, panel web del cerebro (8767), reiniciar el cerebro, arrancar
  con Windows, salir.
- `hotkeys.py`: atajos globales con `RegisterHotKey`. Por defecto **Ctrl+Alt+Shift+M** micro, **Ctrl+Alt+C**
  cámara, **Ctrl+Alt+S** dormir. `Ctrl+Alt+M` (lo acordado) lo tiene otra aplicación de este PC (también
  `Ctrl+Alt+R`); se cambian en `config.json`, clave `hotkeys`, y si alguno está cogido la bandeja lo avisa.
- Interruptores visibles: iconos rojos de micro/cámara tachados en la esquina de la cara + punto rojo en la bandeja.
  Micro apagado = no se manda nada al cerebro. Cámara: el interruptor existe; la webcam llega en la fase 5.
- Dormir = como el robot físico: se lo pide al cerebro (`POST /api/sleep`): cabeza al centro, cara de sueño,
  reloj, y "oye Rocky" lo despierta. Sin cerebro, solo la cara.
- La cara no sale en la barra de tareas ni en Alt+Tab (la app vive en la bandeja); Alt+F4 la oculta.
- Una sola copia (mutex con nombre); la segunda avisa y sale.
- Arrancar con Windows: `HKCU\…\Run\DeskRobotVirtual` → `pythonw run_virtual_robot.pyw`; sin consola, la salida va
  a `%APPDATA%\desk-robot-virtual\app.log`. **Se activa desde la bandeja** (el entorno de trabajo no me dejó escribir
  el registro yo).

**Probado de verdad** (la app completa controlada por script, con pulsaciones reales de teclado): el cerebro lo
arranca la app y conecta en ~3 s; icono en la bandeja; atajos registrados; segunda copia rechazada; micro apagado
por código y encendido con `Ctrl+Alt+Shift+M` (indicador rojo aparece y desaparece); cámara con `Ctrl+Alt+C`;
`Ctrl+Alt+S` cambia el estado de sueño; ocultar/mostrar; fuera de la barra de tareas; al salir el cerebro se cierra;
`brain.log` sin token ni clave. 21 tests de `desktop/`.

**Fallos encontrados**: (1) la comprobación de copia única leía mal el último error de Win32 (arreglado con
`use_last_error`). (2) Dormir por la API devolvía HTTP 500 "Event loop is closed": un cerebro arrancado antes desde
una terminal se quedó a medio cerrar con el puerto 8767 ocupado, así que las órdenes iban a él. No es un fallo de la
app; ahora lo detecta y avisa.

**No probado por mí**: clics en el menú de la bandeja con el ratón, el arranque real al iniciar sesión.

---

## FASE 5 — Webcam (presencia, sonrisa, saludo, ver)

**Cómo está hecho** (`virtual_robot/camera.py`, enganchado en `link.py`)

- La webcam responde a lo que el cerebro ya pide a la placa: `stream {on, fps, size}` → frames `0x02`;
  `snapshot {size}` → un `0x03`. Sin cambios en `server/`.
- Captura a 1280×720 por DirectShow (esta Logitech StreamCam da 10 fps ahí; 30 fps a 640×480). Stream reducido a
  640 px de ancho (320 en `qvga`), 8 fps mientras habla y 5 dormido como el firmware; la foto nítida es el frame
  entero (1024 px para `xga`), sin reabrir la cámara.
- Orientación: cada imagen va espejada porque el cerebro espeja (`CAMERA_MIRROR`, fijo en `config.py`, pensado para
  el sensor del robot); y al conectar se pone `camera_rotate` a 0 por la API (era 270 por la cámara de lado del V2).
  **Queda guardado en `server/settings.json`**: si se monta el robot físico, volver a 270 en el dashboard.
- Elección de cámara: la primera que no dé imagen negra. En este PC el índice 0 es una cámara virtual negra (61 fps
  de negro) y la real es la 1. Se puede fijar con `"camera_index"` en `%APPDATA%\desk-robot-virtual\config.json`.
- La webcam solo está abierta mientras el cerebro pide imagen y el interruptor está encendido; con la cámara
  apagada (Ctrl+Alt+C o bandeja) se libera y se apaga su luz. Ojo: como la placa, mientras el cerebro está
  conectado pide imagen siempre, también dormido (5 fps, para ver un saludo).
- Panel de depuración: estado de la cámara y lo que nota el cerebro ("1 persona(s) · te mira · sonríe · saludo").

**Qué detecta y qué hace con ello** (todo del cerebro original)

- Presencia, mirada, sonrisa, ojos cerrados: MediaPipe face landmarker. Se usa en la nota que acompaña a las
  preguntas visuales y en el panel; con cada pregunta va además la foto de contexto, así que "sabe si estás".
  **Dormido solo vigila las manos**: la presencia se ve con Rocky despierto.
- Saludo con la mano: lo despierta (dice su línea `wake`).
- Preguntas visuales ("¿qué ves?", "mira esto"): foto nítida.
- Distancia aproximada: usa el campo de visión del objetivo del robot (104°), no el de la webcam (~70°), así que
  los metros que dice son orientativos.

**Probado de verdad** (con tu webcam): conexión, giro 270→0, el cerebro recibe imagen; despierto detecta 1 persona
que le mira; "¿qué ves?" → describe la estantería y las figuras con la foto nítida; cámara apagada → webcam liberada
y "No puedo ver nada ahora mismo, cámara no da imagen"; al encenderla vuelve. Frame orientado bien. 26 tests.

**No probado por mí**: el saludo para despertarle (necesita que saludes), la sonrisa en vivo.

**Pendiente**

- Seguimiento de cara (aplazado): con la webcam fija, "sígueme" o **"mírame"** encienden el seguimiento y la cabeza
  virtual se iría al tope (el tracker supone cámara en la cabeza). Solución prevista: cámara pan-tilt virtual
  (fase 0, punto d).
- Modo concentración: necesita `OPENAI_API_KEY` (Decisions API) o cambiarlo por Haiku / detector local.

### Medición de eco con altavoces (2026-11-16)

Micro "Logitech StreamCam" + "Altavoces (USB2.0 Device)", ambos MME; voz de reserva (Helena) con el nivelado del
cerebro, volumen 0,7; VAD Silero del cerebro sobre la grabación; 3 repeticiones:

- Ruido de la sala: VAD máximo 0,20 en silencio (umbral del cerebro 0,4).
- El micro oye la voz 0,52 s después de empezar: el altavoz USB tarda ~0,12 s más de los 0,2 s que declara.
- El último trozo con pinta de voz llega 0,65 s **antes** de `speak_done` (la voz termina con silencio); sin cola
  de reverberación apreciable. → `ECHO_TAIL_S = 0,35 s` sobra; no se cambia.
- Riesgos: una voz que acabe en seco (Fish) deja ~0,23 s de margen real; con Bluetooth puede no bastar. Ajustable con
  `"echo_tail_s"` en `%APPDATA%\desk-robot-virtual\config.json`.
- La boca puede ir ~0,1 s adelantada respecto al sonido en estos altavoces (usa la latencia declarada).

---

## Voz: Fish Audio gratis con `s2.1-pro-free` (2026-11-16)

- La API de Fish va aparte de los planes de la web, por uso (`s2.1-pro` 15 $/M bytes UTF-8), pero tiene un modelo
  **`s2.1-pro-free` a 0 $** (docs.fish.audio, pricing-and-rate-limits; condiciones no explicadas).
- Nuevo ajuste `FISH_TTS_MODEL` en `server/.env` (`brain/config.py`): elige el modelo de Fish sin tocar código y gana
  al del personaje. Con `FISH_TTS_MODEL=s2.1-pro-free` + `FISH_AUDIO_API_KEY`, Rocky habla con su voz clonada.
- Probado: síntesis directa (6,6 s de audio, primer trozo a 1,38 s) y pregunta completa por el cerebro (primer audio a
  1,95 s del final de la pregunta, ~0,25 s más que la voz de Windows), sin caer a la voz de reserva.
- Si Fish dejara de aceptarlo, el cerebro cae solo a la voz de Windows ("fish audio failed, using the built-in voice").
- Voces locales probadas antes (Piper davefx/sharvard, Kokoro dora/alex/santa): no convencieron. Alternativa futura:
  clonación local en la GPU (RTX 4070 SUPER) con XTTS-v2 o Chatterbox.

---

## Paquetes de personajes (2026-11-16)

- `desktop/characters/<id>/package.json`: nombre, descripción, **cara** (pack del cerebro), y la ficha que ya entiende
  el cerebro (`brain/characters.py`: voz de Fish, prompt, ejemplos, frases fijas, palabras de activación), más un
  bloque `"es"` con ejemplos, frases y variantes de activación en español. Rocky es `builtin` (su personalidad sigue
  en `personality.py` / `language.py`).
- `virtual_robot/characters.py`: activar = `brain.characters.save()` en `server/characters/<id>.json` +
  `brain.settings.update()` de `character.id` y `face.pack` (misma validación que el dashboard) y reiniciar el
  cerebro (si lo arrancó la app; si no, avisa).
- Bandeja: submenú **Personaje** con los paquetes (marca el activo).
- Incluidos: **Rocky** (cara Default) y **Jarvis** (voz Fish `34a174c4…`, cara Visor; mayordomo británico, "señor",
  "usted"). Ambos fan work, uso personal.
- Probado de punta a punta: Rocky → Jarvis (cerebro reiniciado como "Jarvis brain server", cara Visor, respuesta
  "Estoy en perfectas condiciones, señor, dentro de lo que cabe para un robot de sobremesa…" con su voz de Fish) →
  Rocky (cara Default). 31 tests de `desktop/`, cada paquete validado con `brain.characters.clean` en en/es.
- Pendiente: cada personaje con su propio estilo de dibujo y animaciones (fase 6); el reloj del cerebro sale en 12 h
  por defecto (cambiar en el dashboard).
