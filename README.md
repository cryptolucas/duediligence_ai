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
http://localhost:3000, vaya a **Nueva operación** y pulse **Abrir caso demo**. Para usar IA, copie
`backend/.env.example` a `backend/.env` y agregue una clave **gratuita** de Groq (`GROQ_API_KEY`, <https://console.groq.com/keys>);
sin claves todo funciona con reglas deterministas.

**Despliegue gratuito con enlace público en una sola plataforma** (Render: un servicio + base de datos; IA con Groq): ver
[DESPLIEGUE.md](DESPLIEGUE.md). El [`Dockerfile`](Dockerfile) compila el frontend como sitio estático (`STATIC_EXPORT=1`) y el
backend lo sirve en la misma URL que la API (`FRONTEND_DIR`), así que no hay CORS ni dos plataformas que conectar.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura backend/frontend, esquemas Pydantic, benchmarks por CIIU, caso demo con citas | ✅ |
| 2 | Motor financiero determinista + tests | ✅ |
| 3 | Parsers PDF/Excel/CSV, grafo LangGraph de 5 nodos, persistencia, endpoints de deals/recálculo/chat | ✅ |
| 4 | Frontend Next.js: carga, workspace dividido, memo con citas, sandbox de EBITDA, red flags, inspector y chat | ✅ |
| 5 | Pruebas con usuarios: casillas obligatorias con validación, «Otros archivos», IA gratuita (Groq), despliegue gratuito | ✅ |

## Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows (Linux/macOS: .venv/bin/python)
copy .env.example .env                                     # opcional: GROQ_API_KEY (gratuita)
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
| GET | `/api/llm/status` | Modelo de IA gratuito disponible (y respaldo) y si Ollama responde |
| GET | `/api/benchmarks` | Benchmarks por CIIU |
| GET | `/api/upload-requirements` | Casillas de carga: qué subir, qué debe contener, formatos y ejemplos |
| POST | `/api/documents/validate` | `file` + `slot` → estado (`valid`/`warning`/`error`), resumen, problemas con «cómo solucionarlo» y casilla sugerida |
| GET | `/api/deals` | Operaciones del navegador que las creó (cabecera `X-Workspace-Id`) con KPIs |
| GET | `/api/deals/{id}` | Expediente, cálculos del motor, memo renderizado, bitácora y chat |
| POST | `/api/deals/upload` | `use_demo=true` → 201 con el expediente. Documentos por casilla (`trial_balance_files`, `financial_statements_files`, `chamber_certificate_files` obligatorios; `other_files` opcional) + `llm_mode` → se validan y parsean al instante; si falta un obligatorio o un archivo no pasa la validación responde **422** con la lista de problemas; si no, **202** con el estado del job y el grafo corre en segundo plano |
| GET | `/api/deals/{id}/status` | Progreso del job: nodo actual, % (nodos completados), llamadas LLM, eventos, error |
| GET | `/api/jobs` | Procesamientos en curso o fallidos |
| POST | `/api/deals/{id}/recalculate` | Toggles de ajustes, ajustes manuales, descartar red flags; recálculo determinista |
| POST | `/api/deals/{id}/chat` | Preguntas sobre fuentes y simulación de escenarios |

### Modos de procesamiento

| Modo | Cuándo | Qué hace |
|---|---|---|
| `CLOUD_API` | Hay `GROQ_API_KEY` (o `OPENROUTER_API_KEY`, `CEREBRAS_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `LLM_BASE_URL`) | Agentes LLM con un modelo abierto gratuito (por defecto Groq · Llama 3.3 70B, respaldo gpt-oss-120b) vía API compatible con OpenAI + guardián de citas + motor determinista |
| `LOCAL_OLLAMA` | Se pidió modo confidencial y Ollama responde | Igual, con un modelo local |
| `RULES_FALLBACK` | No hay claves, o Ollama no responde | Parser + reglas PUC + regex del certificado + reglas del escéptico + memo plantilla |
| `SEED_FALLBACK` | Caso demo | Salidas curadas del seed; el motor recalcula de verdad |

Si se pide `LOCAL_OLLAMA` y Ollama no responde, el deal **nunca** se envía a la nube: cae a `RULES_FALLBACK`.
Si el modelo de `OLLAMA_MODEL` no está descargado, se usa el primero instalado (ver `GET /api/llm/status`), con
una ventana de contexto de `OLLAMA_NUM_CTX` (32.768 por defecto). Con un modelo de 8B en CPU/GPU modesta, cada
llamada puede tardar minutos. Por eso el procesamiento de documentos propios es asíncrono: la carga responde de
inmediato y `/deals/[id]` muestra el avance nodo por nodo (LangGraph en modo streaming), incluida cada llamada al LLM.
Si el servidor se reinicia a mitad de un procesamiento, el job queda marcado como fallido al arrancar.

### Documentos: casillas obligatorias y «Otros archivos»

| Casilla | Formatos | Para qué |
|---|---|---|
| 1 · Balance de prueba (obligatorio, hasta 3) | XLSX, XLS, XLSM, CSV | Única fuente de cifras del motor. Se valida: cuentas PUC, saldos, año identificable, clases 1 y 4. |
| 2 · Estados financieros con notas (obligatorio, hasta 3) | PDF digital | Notas → ajustes al EBITDA, deudas, litigios, partes relacionadas. Se valida: estados y notas presentes, texto legible. |
| 3 · Certificado de existencia y representación legal (obligatorio, 1) | PDF digital | Razón social, NIT y CIIU (múltiplos). Se valida el tipo de documento, el NIT y la antigüedad (>30 días = advertencia). |
| Otros archivos (opcional, hasta 10) | PDF, DOCX, XLSX, XLS, CSV, TXT | Contexto complementario: teaser, avalúos, contratos, cartera, actas… |

Cada archivo se revisa al cargarlo (vacío, dañado, protegido con contraseña, escaneado sin texto, formato o tipo de documento
equivocado) y se indica cómo solucionarlo y, si aplica, en qué casilla va. El servidor repite la validación al generar el expediente.

Salvaguardas de «Otros archivos» (`upload_slot = OTHER`): nunca alimentan el motor (sus filas de balance se descartan), nunca son
fuente autoritativa (datos societarios quedan `UNVERIFIED`), los ajustes de EBITDA que solo se apoyan en ellos quedan
`PENDING_REVIEW`, las páginas sin información relevante no se envían al modelo, ocupan como máximo ~35 % del contexto cuando las
fuentes principales no caben, y se avisa si un documento parece de otra empresa (otro NIT). Los prompts etiquetan cada bloque como
`[FUENTE PRINCIPAL]` o `[FUENTE COMPLEMENTARIA]` y exigen reportar contradicciones en lugar de resolverlas.

### Piezas clave

- `app/schemas/deal.py` — `SourceCitation`, `MappedAccountItem`, `EbitdaAdjustment`, `RedFlagItem`, `MissingInfoItem` y el expediente `DealDossier`, que rechaza citas a documentos inexistentes. Los `CitedFact` sin fuente deben ir como `MISSING_DATA`.
- `app/services/financial_engine.py` — toda la aritmética (márgenes, YoY/CAGR, puente de EBITDA, capital de trabajo, deuda neta, ecuación contable, valoración P25/mediana/P75, exposición a contingencias). Solo depende de la librería estándar y los esquemas; los tests lo verifican.
- `app/services/document_parser.py` — PDF (PyMuPDF, con pdfplumber como alternativa) reagrupado por renglón visual, con columnas unidas por ` | ` y coordenadas por línea. Excel/CSV serializado por fila. Detecta balances de prueba: encabezados, columna de saldo final, periodo y cuentas hoja (evita sumar niveles agregados 1/11/1105).
- `app/services/puc_mapper.py` — clasificación PUC por prefijo, detección de la convención de signos del export (Siigo: créditos negativos) y de balances pre-cierre.
- `app/services/citation_guard.py` — toda cita propuesta por un LLM se verifica literalmente contra el documento; si no aparece, la afirmación se descarta. Los montos de ajustes se convierten a COP por código según las unidades del documento, y si la cifra no aparece en la cita, el ajuste queda `PENDING_REVIEW`.
- `app/services/document_validation.py` — casillas de carga (textos para la interfaz) y validación determinista por casilla.
- `app/services/llm_client.py` — cliente HTTP compatible con OpenAI (sin SDKs pesados) y Ollama nativo: reintentos ante 429
  respetando `retry-after`, modelo de respaldo, reducción automática del contexto si el proveedor lo rechaza por tamaño.
- `app/agents/context.py` — jerarquía de fuentes, filtro de relevancia y troceo del contexto (`plan_context`, `run_chunked`):
  documentos largos se analizan por partes y los resultados se fusionan sin duplicados.
- `app/agents/graph.py` — grafo LangGraph: ingesta → analista financiero/societario → motor determinista → escéptico → redactor.
- `app/services/memo_renderer.py` — el memo del agente usa marcadores (`{{metric:ebitda_adjusted:2025}}`) que se llenan con la salida del motor. Así, cada toggle actualiza el memo sin llamar al LLM. Si el modelo escribe cifras propias en lugar de marcadores (menos de 5), se le pide corregir una vez y, si insiste, se usa la plantilla determinista: ninguna cifra del memo sale de la aritmética del LLM.
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
| `/deals/new` | Caso demo; tres casillas obligatorias y «Otros archivos» con instrucciones, formatos y ejemplos; validación en vivo por archivo con «cómo solucionarlo» y botón «Mover a…»; el botón *Generar expediente* se habilita solo cuando todo es válido |
| `/deals/[id]` | Workspace 60/40. **Izquierda:** encabezado (NIT, CIIU, cuadre contable, COP millones/USD con TRM editable), KPIs y tres pestañas: memo con badges de cita; financieros con puente de EBITDA (switches, ajustes manuales, valoración, tablas históricas con cifras clicables); red flags, información faltante y perfil societario. **Derecha:** inspector de evidencia con la cita resaltada y chat con el expediente |

Las cifras de las tablas y del memo vienen del motor del backend. El frontend solo cambia la unidad de presentación;
la conversión a USD usa la TRM que digita el analista (por defecto 4.000, un supuesto editable).

En Windows, apunte el frontend a `127.0.0.1` y no a `localhost`: resolver `localhost` por IPv6 añade unos 200 ms a cada llamada.
