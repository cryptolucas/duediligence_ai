# Catalejo Deal Desk — MVP

Screening financiero y due diligence preliminar AI-First para fondos de Private Equity (lower-middle-market),
Family Offices y bancas de inversión boutique en Colombia y Latinoamérica.

## Inicio rápido (backend + frontend a la vez)

Requisitos: Python 3.11+ y Node.js 18+.

Windows (PowerShell):

```bash
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

macOS / Linux / Git Bash:

```bash
./dev.sh
```

La primera vez, el script crea `backend/.venv`, instala dependencias y ejecuta `npm install`. Después abra
http://localhost:3000, vaya a **Nueva operación** y pulse **Abrir caso demo en 1 clic**. Para usar un LLM, copie
`backend/.env.example` a `backend/.env` y agregue una API key; sin claves todo funciona con reglas deterministas.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura backend/frontend, esquemas Pydantic, benchmarks por CIIU, caso demo con citas | ✅ |
| 2 | Motor financiero determinista + tests | ✅ |
| 3 | Parsers PDF/Excel/CSV, grafo LangGraph de 5 nodos, persistencia, endpoints de deals/recálculo/chat | ✅ |
| 4 | Frontend Next.js: carga, workspace dividido, memo con citas, sandbox de EBITDA, red flags, inspector y chat | ✅ |

## Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows (Linux/macOS: .venv/bin/python)
copy .env.example .env                                     # opcional: claves de LLM
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Para probar la carga de archivos propios con documentos reales del caso demo (XLSX + PDF):

```bash
.venv/Scripts/python scripts/export_demo_documents.py   # crea backend/demo_files/
```

### Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/llm/status` | Modelo cloud disponible y si Ollama responde |
| GET | `/api/benchmarks` | Benchmarks por CIIU |
| GET | `/api/deals` | Lista de operaciones con KPIs |
| GET | `/api/deals/{id}` | Expediente, cálculos del motor, memo renderizado, bitácora y chat |
| POST | `/api/deals/upload` | Multipart: `files[]` (PDF/XLSX/CSV), `llm_mode` (`CLOUD_API`/`LOCAL_OLLAMA`), o `use_demo=true` |
| POST | `/api/deals/{id}/recalculate` | Toggles de ajustes, ajustes manuales, descartar red flags; recálculo determinista |
| POST | `/api/deals/{id}/chat` | Preguntas sobre fuentes y simulación de escenarios |

### Modos de procesamiento

| Modo | Cuándo | Qué hace |
|---|---|---|
| `CLOUD_API` | Hay `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` u `OPENAI_API_KEY` | Agentes LLM vía LiteLLM + guardián de citas + motor determinista |
| `LOCAL_OLLAMA` | Se pidió modo confidencial y Ollama responde | Igual, con un modelo local |
| `RULES_FALLBACK` | No hay claves, o Ollama no responde | Parser + reglas PUC + regex del certificado + reglas del escéptico + memo plantilla |
| `SEED_FALLBACK` | Caso demo | Salidas curadas del seed; el motor recalcula de verdad |

Si se pide `LOCAL_OLLAMA` y Ollama no responde, el deal **nunca** se envía a la nube: cae a `RULES_FALLBACK`.
Si el modelo de `OLLAMA_MODEL` no está descargado, se usa el primero instalado (ver `GET /api/llm/status`), con
una ventana de contexto de `OLLAMA_NUM_CTX` (32.768 por defecto). Con un modelo de 8B en CPU/GPU modesta, cada
llamada puede tardar minutos; el procesamiento completo de un deal es síncrono y puede tomar bastante tiempo.

### Piezas clave

- `app/schemas/deal.py` — `SourceCitation`, `MappedAccountItem`, `EbitdaAdjustment`, `RedFlagItem`, `MissingInfoItem` y el expediente `DealDossier`, que rechaza citas a documentos inexistentes. Los `CitedFact` sin fuente deben ir como `MISSING_DATA`.
- `app/services/financial_engine.py` — toda la aritmética (márgenes, YoY/CAGR, puente de EBITDA, capital de trabajo, deuda neta, ecuación contable, valoración P25/mediana/P75, exposición a contingencias). Solo depende de la librería estándar y los esquemas; los tests lo verifican.
- `app/services/document_parser.py` — PDF (PyMuPDF, con pdfplumber como alternativa) reagrupado por renglón visual, con columnas unidas por ` | ` y coordenadas por línea. Excel/CSV serializado por fila. Detecta balances de prueba: encabezados, columna de saldo final, periodo y cuentas hoja (evita sumar niveles agregados 1/11/1105).
- `app/services/puc_mapper.py` — clasificación PUC por prefijo, detección de la convención de signos del export (Siigo: créditos negativos) y de balances pre-cierre.
- `app/services/citation_guard.py` — toda cita propuesta por un LLM se verifica literalmente contra el documento; si no aparece, la afirmación se descarta. Los montos de ajustes se convierten a COP por código según las unidades del documento, y si la cifra no aparece en la cita, el ajuste queda `PENDING_REVIEW`.
- `app/agents/graph.py` — grafo LangGraph: ingesta → analista financiero/societario → motor determinista → escéptico → redactor.
- `app/services/memo_renderer.py` — el memo del agente usa marcadores (`{{metric:ebitda_adjusted:2025}}`) que se llenan con la salida del motor. Así, cada toggle actualiza el memo sin llamar al LLM.
- `app/services/chat.py` — en las preguntas de escenario, el motor recalcula antes y después; el LLM, si lo hay, solo redacta y elige qué ajustes probar.
- `app/data/demo_deal_seed.json` — caso sintético "Alimentos y Conservas del Oriente S.A.S.". Se regenera con `python scripts/build_demo_seed.py`; un test exige que el JSON coincida con el generador.
- `app/data/supersociedades_benchmarks.json` — **valores referenciales, no oficiales** (ver `_meta.disclaimer`). Hay que recalibrarlos con datos del PIE de Supersociedades y con transacciones comparables antes de usarlos en un Comité real.

### Convención de signos (`raw_value_cop`, COP plenos)

Ingresos, activos, pasivos y patrimonio van positivos; costos y gastos también van positivos (magnitud del gasto).
Las cuentas correctoras (devoluciones 4175, deterioro 1399 y depreciación acumulada 1592) van negativas.
En `OTHER_OP_INCOME_EXP`, positivo es ingreso y negativo es gasto. En `NET_INTEREST`, positivo es gasto neto.
Las cuentas `UNMAPPED` se reportan, pero nunca entran a los cálculos.

## Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000 (proxy /api -> http://127.0.0.1:8000)
```

| Ruta | Contenido |
|---|---|
| `/` | Lista de operaciones con KPIs, red flags y estado de cuadre |
| `/deals/new` | Caso demo en 1 clic; Dropzone PDF/XLSX/CSV; selector `Cloud API` / `Local Ollama` con disponibilidad real |
| `/deals/[id]` | Workspace 60/40. **Izquierda:** encabezado (NIT, CIIU, cuadre contable, COP millones/USD con TRM editable), KPIs y tres pestañas: memo con badges de cita; financieros con puente de EBITDA (switches, ajustes manuales, valoración, tablas históricas con cifras clicables); red flags, información faltante y perfil societario. **Derecha:** inspector de evidencia con la cita resaltada y chat con el expediente |

Las cifras de las tablas y del memo vienen del motor del backend. El frontend solo cambia la unidad de presentación;
la conversión a USD usa la TRM que digita el analista (por defecto 4.000, un supuesto editable).

En Windows, apunte el frontend a `127.0.0.1` y no a `localhost`: resolver `localhost` por IPv6 añade unos 200 ms a cada llamada.
