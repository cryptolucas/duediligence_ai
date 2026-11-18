# Guía de despliegue gratuito — Catalejo Deal Desk (una sola plataforma)

Esta guía le lleva, paso a paso y sin conocimientos de infraestructura, a tener **un enlace público** para compartir con los
usuarios de prueba. Todo queda en **una sola plataforma (Render)**, en el plan gratuito y **sin tarjeta de crédito**.
Tiempo estimado: 20–30 minutos.

## Qué va a montar

```
 Usuarios de prueba
        │  https://catalejo-xxxx.onrender.com   ← el enlace que va a compartir
        ▼
 ┌────────────────────────────── Render (plan gratuito) ──────────────────────────────┐
 │  Servicio "catalejo"  (un solo contenedor)          Base de datos "catalejo-db"    │
 │  • páginas de la aplicación (frontend)       ───►   PostgreSQL: guarda las         │
 │  • API, motor financiero y agentes                   operaciones                   │
 └───────────────────────────────────┬────────────────────────────────────────────────┘
                                     │ solo una clave (no hay nada que desplegar)
                                     ▼
                              Groq · Llama 3.3 70B (IA gratuita, modelo abierto)
```

El backend sirve también las páginas de la aplicación, así que hay **un único servicio y un único enlace**: no hay que
conectar dos plataformas, ni configurar CORS, ni variables de una plataforma en otra. El archivo [`render.yaml`](render.yaml)
del repositorio describe todo; Render lo lee y crea el servicio y la base de datos con un clic.

**Por qué Render.** Despliega desde GitHub con un archivo de configuración (Blueprint), ofrece servicio web y base de datos
gratuitos en el mismo lugar, ejecuta procesos largos en segundo plano (el análisis tarda minutos) y no pide tarjeta.

**Por qué Groq para la IA.** Modelos **abiertos** (Llama 3.3 70B, con gpt-oss-120b de respaldo), gratis, sin tarjeta y muy
rápidos. Groq no conserva los datos de las solicitudes por defecto (solo registros temporales por abuso, hasta 30 días). La
IA es solo una clave que se pega en Render: no es otra plataforma que administrar.

### Límites del plan gratuito que debe conocer

| Límite | Qué significa en la práctica |
|---|---|
| El servicio **se duerme tras 15 min sin uso** | La primera visita después de un rato tarda ~1 minuto (la aplicación muestra «Conectando con el servidor…»). Luego va normal. |
| La **base de datos gratuita vence a los 30 días** (más 14 de gracia) | Suficiente para una fase de pruebas de 3–4 semanas. Si la prueba durará más, vea «Si las pruebas duran más de 4 semanas» abajo (2 minutos, sigue gratis). |
| 512 MB de memoria | La aplicación usa ~140 MB procesando: hay margen. |
| 750 horas al mes | Alcanza para tener el servicio encendido todo el mes. |
| Límite de tokens por minuto de Groq | Con varios usuarios a la vez un paso puede esperar 30–60 s; el sistema reintenta solo. Máximo 2 análisis simultáneos; los demás hacen fila. |

---

## Paso 0 · Subir el código a GitHub — 2 min

Render despliega desde GitHub. El proyecto ya tiene el repositorio `cryptolucas/duediligence_ai`. En la carpeta del proyecto:

```bash
git add -A
git commit -m "Preparar despliegue en Render"
git push
```

Si el repositorio es privado, no hay problema: Render le pedirá permiso para leerlo.

---

## Paso 1 · Crear la clave gratuita de IA (Groq) — 3 min

1. Entre a <https://console.groq.com> y regístrese (correo o cuenta de Google/GitHub).
2. Menú **API Keys** → **Create API Key** → nombre: `catalejo` → **Submit**.
3. **Copie la clave** (empieza por `gsk_...`). Solo se muestra una vez: guárdela en un lugar seguro.
4. (Recomendado) En **Settings → Data Controls** active *Zero Data Retention* si está disponible para su cuenta.

---

## Paso 2 · Desplegar todo en Render — 5 min de su tiempo + 5–10 min de espera

1. Entre a <https://render.com> → **Get Started** → regístrese con **GitHub**.
2. Arriba a la derecha: **New** → **Blueprint**.
3. Elija el repositorio `duediligence_ai` (si no aparece: **Configure account** y dele acceso). Render lee `render.yaml` y
   muestra lo que va a crear: el servicio web **catalejo** y la base de datos **catalejo-db**, ambos en plan **Free**.
4. Le pedirá solo dos valores:

   | Variable | Qué poner |
   |---|---|
   | `GROQ_API_KEY` | La clave del Paso 1 (`gsk_...`). |
   | `ACCESS_CODE` | Un código para los usuarios de prueba, ej. `piloto2026`. Si lo deja vacío, cualquiera con el enlace podrá entrar y gastar su cuota de IA. **Recomendado ponerlo.** |

   La conexión a la base de datos (`DATABASE_URL`) se configura sola.
5. Pulse **Apply** (o **Deploy Blueprint**). La primera vez tarda 5–10 minutos: Render construye la aplicación. Puede ver el
   avance en el servicio **catalejo** → pestaña **Logs**. Cuando termine verá **Live** en verde.
6. Copie la URL del servicio (arriba, bajo el nombre), por ejemplo `https://catalejo-xxxx.onrender.com`.
   **Ese es el enlace para los usuarios.**

---

## Paso 3 · Verificar que todo funciona — 10 min

Haga esta lista antes de compartir el enlace:

1. **Estado del servidor**: abra `https://catalejo-xxxx.onrender.com/api/health` → debe mostrar `"status":"ok"` y
   `"access_code_required":true` (si configuró el código).
2. **Abrir la aplicación**: `https://catalejo-xxxx.onrender.com`. Le pedirá el **código de acceso**; escríbalo.
3. **Caso demo**: *Nueva operación* → **Abrir caso demo**. Debe abrir el expediente con memo, financieros y red flags.
4. **IA activa**: en *Nueva operación*, el Paso 3 debe decir *«Inteligencia artificial: Groq · llama-3.3-70b-versatile»*.
   Si dice *«El servidor no tiene un modelo de IA configurado»*, revise `GROQ_API_KEY` en Render → servicio → **Environment**.
5. **Validación de archivos**: suelte un PDF cualquiera en la casilla *Balance de prueba*: debe marcarlo en rojo, explicar cómo
   solucionarlo y mantener deshabilitado *Generar expediente*.
6. **Análisis completo**: para probar sin documentos reales, genere los del caso demo en su computador:
   ```bash
   cd backend
   .venv/Scripts/python scripts/export_demo_documents.py      # crea backend/demo_files/
   ```
   Cargue el `.xlsx` en la casilla 1, los dos `EEFF_*.pdf` en la 2, el `Certificado_*.pdf` en la 3 y el teaser y el avalúo en
   *Otros archivos*. Pulse **Generar expediente**: verá el avance paso a paso; con Groq tarda unos 2–5 minutos. El expediente
   debe mostrar el modo **«LLM en la nube»** y ajustes de EBITDA propuestos por la IA.
7. **Persistencia**: en Render → servicio → **Manual Deploy → Restart service**. Al volver a abrir el sitio, la operación debe
   seguir en *Operaciones*.
8. **Aislamiento**: abra el enlace en una ventana de incógnito. Tras el código, *Operaciones* debe estar vacía: cada navegador
   ve solo sus operaciones.

---

## Paso 4 · Compartir el enlace

Mensaje sugerido:

> Hola, te comparto la versión de prueba de **Catalejo Deal Desk**: https://catalejo-xxxx.onrender.com
> Código de acceso: **piloto2026**
> 1. Entra a *Nueva operación* y sube en cada casilla: el balance de prueba (Excel), los estados financieros con notas (PDF) y
>    el certificado de Cámara de Comercio (PDF). Si tienes otros documentos útiles (teaser, avalúos, contratos), súbelos en
>    *Otros archivos*.
> 2. Pulsa *Generar expediente*; el análisis tarda unos minutos.
> 3. Si la página tarda en abrir la primera vez, espera un minuto: el servidor se está iniciando.
> Tus operaciones solo se ven en tu navegador. Cualquier error o comentario, escríbeme.

Consejo: antes de una sesión de pruebas en vivo, abra el enlace un par de minutos antes para «despertar» el servidor.

---

## Si las pruebas duran más de 4 semanas (base de datos sin vencimiento)

La base de datos gratuita de Render se borra a los 30 días (+14 de gracia). Si la fase de pruebas será más larga, lo más
sencillo es usar desde el inicio una base gratuita **sin vencimiento** en Neon. Sigue siendo gratis; solo cambia un valor:

1. Entre a <https://neon.tech> → regístrese con GitHub → **Create project** (nombre `catalejo`, región *AWS US West (Oregon)*,
   la misma de Render por defecto).
2. Pulse **Connect** y copie la cadena de conexión (`postgresql://usuario:clave@ep-xxxx.../neondb?sslmode=require`).
3. En Render → servicio **catalejo** → **Environment** → edite `DATABASE_URL`, pegue la cadena de Neon → **Save Changes**.
   El servicio se reinicia y crea las tablas solo.
4. (Opcional) Elimine la base `catalejo-db` de Render.

Las operaciones guardadas en la base anterior no se trasladan: haga este cambio al inicio de las pruebas o avise a los
usuarios. La otra opción es pasar la base de Render a un plan pagado antes del día 30.

---

## Durante las pruebas: qué esperar y cómo resolver problemas

| Situación | Causa | Qué hacer |
|---|---|---|
| La primera carga tarda ~1 min | El servicio gratuito duerme tras 15 min sin uso | Normal. |
| Un paso del análisis se queda quieto 30–60 s | Límite de tokens por minuto de Groq: el sistema espera y reintenta | Normal. |
| El expediente dice «Reglas deterministas» en vez de IA | Clave de Groq inválida o cuota diaria agotada (también falló el respaldo) | Revise los **Logs** del servicio. La cuota diaria se renueva cada 24 h; puede añadir `OPENROUTER_API_KEY` como respaldo. |
| «No pudimos conectar con el servidor» | El servicio está desplegando, caído o despertando | Espere un minuto y reintente; revise **Events/Logs** en Render. |
| «Código de acceso inválido» | Código distinto al de `ACCESS_CODE` | Verifique el valor en Render → Environment. |
| Un análisis quedó «fallido: el servidor se reinició» | Render reinició el servicio a mitad de un análisis (despliegue o inactividad) | Vuelva a cargar los documentos. Evite desplegar cambios mientras hay usuarios probando. |
| Desaparecieron todas las operaciones | Venció la base gratuita (día 30–44) | Ver la sección anterior (Neon). |

**Ver qué pasó en un análisis**: en el expediente, botón **Bitácora** (cada paso, llamadas a la IA y notas: contexto enviado,
documentos complementarios descartados por irrelevantes, ajustes que quedaron pendientes, etc.).

**Actualizar la aplicación**: haga `git push` a la rama `main`; Render vuelve a desplegar solo (5–10 min). Evite hacerlo
mientras haya usuarios con análisis en curso.

---

## Variables de entorno (referencia)

Se ven y editan en Render → servicio **catalejo** → **Environment**. Al guardar, el servicio se reinicia.

| Variable | Cómo se configura | Descripción |
|---|---|---|
| `GROQ_API_KEY` | La pide el Blueprint | Clave de Groq. Sin ella todo funciona con reglas deterministas, sin IA. |
| `ACCESS_CODE` | La pide el Blueprint | Código para entrar. Vacía = acceso libre. |
| `DATABASE_URL` | Automática | Conexión a la base. Cámbiela por la de Neon si necesita más de 30 días. |
| `MAX_CONCURRENT_JOBS` | `render.yaml` (2) | Análisis simultáneos; el resto hace fila. |
| `LLM_MODEL` | Opcional | Cambiar el modelo, ej. `groq/openai/gpt-oss-120b`. |
| `LLM_FALLBACK_MODELS` | Opcional | Modelos de respaldo separados por coma. |
| `LLM_MAX_INPUT_TOKENS` | Opcional | Tamaño de cada parte de contexto (6000 por defecto con Groq; se ajusta solo si el proveedor lo rechaza). |

`FRONTEND_DIR`, `STORAGE_DIR` y `PORT` ya vienen en el `Dockerfile`: no las cambie.

---

## Cambiar de proveedor de IA (opcional)

El backend habla con cualquier API compatible con OpenAI. Basta con añadir la clave correspondiente en Render:

| Proveedor | Variable | Modelo por defecto | Nota |
|---|---|---|---|
| Groq (recomendado) | `GROQ_API_KEY` | `llama-3.3-70b-versatile` + respaldo `openai/gpt-oss-120b` | Abierto, gratis, rápido. |
| OpenRouter | `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct:free` | Pocas solicitudes diarias gratis; útil como respaldo: `LLM_FALLBACK_MODELS=groq/openai/gpt-oss-120b,openrouter/meta-llama/llama-3.3-70b-instruct:free`. |
| Cerebras | `CEREBRAS_API_KEY` | `gpt-oss-120b` | Muy rápido; revise si su plan gratuito sigue vigente. |
| Mistral | `MISTRAL_API_KEY` | `mistral-small-latest` | Modelo abierto; plan gratuito con verificación por teléfono. |
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` | No es abierto y en el plan gratis los datos pueden usarse para entrenar: evítelo con documentos reales. |
| Servidor propio | `LLM_BASE_URL` + `LLM_MODEL` (+ `LLM_API_KEY`) | — | vLLM, LM Studio u Ollama (`/v1`) en un equipo propio. |

---

## Probar la imagen en su computador (opcional)

Con Docker Desktop instalado, desde la carpeta del proyecto:

```bash
docker build -t catalejo .
docker run --rm -p 8000:8000 -e GROQ_API_KEY=gsk_... catalejo
```

Abra <http://localhost:8000>. Sin `DATABASE_URL` usa una base SQLite interna que se borra al detener el contenedor.

---

## Alternativa para más adelante: frontend en Vercel

Si en el futuro quiere el frontend siempre rápido (sin esperar a que el servidor despierte), puede publicarlo aparte en
Vercel: proyecto con *Root Directory* `frontend` y variable `NEXT_PUBLIC_API_BASE_URL` = URL de Render; y en Render, la
variable `CORS_ORIGINS` = URL de Vercel. El código ya lo soporta; para las pruebas no hace falta.

## Costos y cuándo pasar a pago

Todo lo anterior cuesta **$0**. Señales de que conviene pagar cuando el piloto crezca:

- No quiere esperar el arranque en frío → plan Starter de Render para el servicio (siempre encendido).
- Muchos usuarios a la vez o análisis muy grandes → plan pagado de Groq (se paga por uso) para subir los límites por minuto.
- Datos por más de 30 días sin cambiar a Neon → plan pagado de la base de Render.
