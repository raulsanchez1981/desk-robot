# desk-robot: robot virtual para Windows (fork personal)

Este repo es un fork personal del proyecto desk-robot de Casey (`upstream`). Encima va un **robot virtual para
Windows** (`desktop/`) que se conecta al cerebro (`server/`) como la placa ESP32.

**Antes de nada, lee la sección "▶ ESTADO Y CÓMO RETOMAR" al principio de `NOTES.md`.** Tiene el estado, los
pendientes por prioridad, cómo arrancar y probar, dónde está cada ajuste y las trampas conocidas. Debajo están las
notas por fase.

## Reglas de trabajo

- Rama de trabajo `feat/robot-virtual-windows`. Commits pequeños y push a `origin` sin preguntar; nunca a `main`
  ni a `upstream` (push deshabilitado).
- Conventional Commits en español (`feat:`, `fix:`, `docs:`…).
- Al cerrar cada bloque: actualizar `NOTES.md` (la sección de estado y una nota del bloque) y resumir al usuario qué
  funciona, qué se probó de verdad y qué no, y qué decisión necesita.
- `server/` es de Casey: cambios pequeños y localizados (mejor en módulos nuestros como `brain/language.py` o
  `brain/memory.py`, con enganches mínimos) para que `git merge upstream/main` no duela. Lo nuevo va en `desktop/`.
- Secretos (`server/.env`, tokens, claves) nunca se commitean ni se imprimen; los logs se enmascaran.
- Código en inglés; comentarios en español solo cuando la lógica no sea evidente; respuestas al usuario en español.
- `desktop/virtual_robot/ui/facekit.js` es generado (`desktop/tools/sync_facekit.py`): no editarlo a mano.
- Reemplazos con `\b`, `\n` o `\\` dentro de heredocs de bash se corrompen: usar la herramienta Edit para esos.

## Comandos

    cd desktop && ..\server\.venv\Scripts\python -m virtual_robot --debug          # la app completa
    cd server  && .venv\Scripts\python -m unittest discover -s tests -p "test_*.py"  # tests del cerebro
    cd desktop && ..\server\.venv\Scripts\python -m unittest discover -s tests        # tests de la app
