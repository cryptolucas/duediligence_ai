#!/usr/bin/env bash
# Levanta backend (FastAPI :8000) y frontend (Next.js :3000) en macOS / Linux / Git Bash.
# Uso:  ./dev.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -x "$ROOT/backend/.venv/bin/python" ]; then
  PY="$ROOT/backend/.venv/bin/python"
elif [ -x "$ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/backend/.venv/Scripts/python.exe"
else
  echo "Creando entorno virtual de Python e instalando dependencias..."
  python3 -m venv "$ROOT/backend/.venv"
  PY="$ROOT/backend/.venv/bin/python"
  "$PY" -m pip install -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Instalando dependencias del frontend..."
  (cd "$ROOT/frontend" && npm install)
fi

(cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM

echo "Backend  -> http://127.0.0.1:8000/docs"
echo "Frontend -> http://localhost:3000  (Ctrl+C para detener ambos)"
cd "$ROOT/frontend" && npm run dev
