# Guía de despliegue gratuito — Catalejo Deal Desk

Esta guía le lleva, paso a paso y sin conocimientos de infraestructura, a tener **un enlace público** para compartir con los
usuarios de prueba. Todo usa planes gratuitos y **no pide tarjeta de crédito**. Tiempo estimado: 30 a 45 minutos.

## Qué va a montar

```
 Usuarios de prueba
        │  https://catalejo-xxxx.vercel.app   ← el enlace que va a compartir
        ▼
 ┌──────────────┐  llamadas /api   ┌──────────────────┐   guarda      ┌─────────────┐
 │   Vercel     │ ───────────────► │     Render       │ ────────────► │    Neon     │
 │  (frontend   │                  │ (backend FastAPI │               │ (PostgreSQL)│
 │   Next.js)   │                  │  + motor + IA)   │ ───┐          └─────────────┘
 └──────────────┘                  └──────────────────┘    │ IA
                                                           ▼
                                                    ┌─────────────┐
                                                    │    Groq     │  Llama 3.3 70B (modelo abierto)
                                                    └─────────────┘
```

| Componente | Plataforma | Por qué esta | Límites del plan gratuito que importan |
|---|---|---|---|
| Frontend (Next.js) | **Vercel** (Hobby) | Es la plataforma creadora de Next.js: se conecta a GitHub y despliega solo, sin configuración. Responde al instante (no "duerme"). | Uso personal/no comercial. Para un piloto de pruebas sirve; si se vuelve comercial, pase a Pro o use Netlify. |
| Backend (FastAPI) | **Render** (Free) | Despliega Python desde GitHub con el archivo `render.yaml` ya incluido en el repositorio. Admite procesos largos en segundo plano (el análisis tarda minutos). | 512 MB de RAM (el backend usa ~180 MB). **Se duerme tras 15 min sin uso** y tarda ~1 min en despertar. Disco temporal: por eso la base va en Neon. 750 h/mes. |
| Base de datos | **Neon** (Free) | PostgreSQL gratuito que no caduca (la base gratuita de Render se borra a los 30 días). Las operaciones sobreviven a reinicios. | ~0,5–1 GB de almacenamiento: alcanza para cientos de operaciones. |
| Inteligencia artificial | **Groq** (Free) | Modelos **abiertos** (Llama 3.3 70B y gpt-oss-120b de respaldo), gratis, sin tarjeta y muy rápidos. Groq no conserva los datos de las solicitudes por defecto (solo registros temporales por abuso, hasta 30 días). | Límite de tokens por minuto y por día. El sistema lo maneja solo: trocea los documentos, espera y reintenta, y usa el modelo de respaldo. |

> **Por qué Groq y no otra opción.** Gemini (Google) tiene un plan gratis generoso, pero no es un modelo abierto y en el plan
> gratuito Google puede usar los datos enviados para mejorar sus productos: no es adecuado para estados financieros reales.
> OpenRouter ofrece modelos `:free` pero con muy pocas solicitudes diarias. Correr un modelo propio (Ollama) en un servidor
> gratuito es inviable: no hay planes gratis con la memoria necesaria y cada paso tardaría muchos minutos. El código admite
> todas estas alternativas cambiando solo variables de entorno (ver «Cambiar de proveedor de IA» al final).

---

## Paso 0 · Subir el código a GitHub

Render y Vercel despliegan desde GitHub. El proyecto ya tiene el repositorio `cryptolucas/duediligence_ai`.

1. Confirme que los últimos cambios están subidos (en la carpeta del proyecto):
   ```bash
   git add -A
   git commit -m "Preparar despliegue"
   git push
   ```
2. Si el repositorio es **privado**, no hay problema: Render y Vercel le pedirán permiso para leerlo.

---

## Paso 1 · Crear la clave gratuita de IA (Groq) — 3 min

1. Entre a <https://console.groq.com> y regístrese (correo o cuenta de Google/GitHub).
2. Menú **API Keys** → **Create API Key** → nombre: `catalejo` → **Submit**.
3. **Copie la clave** (empieza por `gsk_...`). Solo se muestra una vez: guárdela en un lugar seguro.
4. (Recomendado) En **Settings → Data Controls** active *Zero Data Retention* si está disponible para su cuenta.

---

## Paso 2 · Crear la base de datos (Neon) — 5 min

1. Entre a <https://neon.tech> → **Sign up** (puede usar su cuenta de GitHub).
2. **Create project** → nombre `catalejo` → región **AWS US East (N. Virginia)** (la más cercana a Render Virginia) → **Create**.
3. En el panel del proyecto pulse **Connect**. Copie la **cadena de conexión** completa; se ve así:
   ```
   postgresql://usuario:clave@ep-xxxx.us-east-1.aws.neon.tech/neondb?sslmode=require
   ```
   Péguela tal cual más adelante; el backend la adapta solo. No necesita crear tablas: se crean al arrancar.

---

## Paso 3 · Desplegar el backend (Render) — 10 min

1. Entre a <https://render.com> → **Get Started** → regístrese con **GitHub**.
2. Arriba a la derecha: **New** → **Blueprint**.
3. Elija el repositorio `duediligence_ai` (si no aparece: **Configure account** y dele acceso). Render detecta el archivo
   `render.yaml` y propone el servicio **catalejo-api** en el plan **Free**.
4. Le pedirá estas variables:

   | Variable | Qué poner |
   |---|---|
   | `GROQ_API_KEY` | La clave del Paso 1 (`gsk_...`). |
   | `DATABASE_URL` | La cadena de Neon del Paso 2 (`postgresql://...`). |
   | `CORS_ORIGINS` | Por ahora escriba `http://localhost:3000`. La cambiará en el Paso 5 por el enlace de Vercel. |
   | `ACCESS_CODE` | Un código para los usuarios de prueba, ej. `piloto2026`. Si lo deja vacío, cualquiera con el enlace podrá entrar (y gastar su cuota de IA). **Recomendado ponerlo.** |

5. Pulse **Apply** / **Deploy Blueprint**. La primera vez tarda 3–6 minutos. Cuando termine verá **Live** en verde.
6. Copie la URL del servicio (arriba, bajo el nombre), por ejemplo `https://catalejo-api.onrender.com`.

**Verificación rápida del backend** (en el navegador):

- `https://catalejo-api.onrender.com/api/health` → debe mostrar `"status":"ok"`.
- `https://catalejo-api.onrender.com/api/upload-requirements` → con código de acceso responderá *"Código de acceso inválido o
  faltante"*: es correcto, significa que la protección funciona.

Si algo falla, abra el servicio en Render → pestaña **Logs**: ahí aparece el error.

---

## Paso 4 · Desplegar el frontend (Vercel) — 7 min

1. Entre a <https://vercel.com> → **Sign Up** → **Continue with GitHub** → plan **Hobby**.
2. **Add New… → Project** → **Import** el repositorio `duediligence_ai`.
3. En la configuración del proyecto:
   - **Root Directory**: pulse **Edit** y elija la carpeta **`frontend`** (importante).
   - **Framework Preset**: Next.js (se detecta solo). No cambie los comandos de build.
   - **Environment Variables**: agregue
     | Nombre | Valor |
     |---|---|
     | `NEXT_PUBLIC_API_BASE_URL` | La URL de Render del Paso 3, **sin `/` al final**, ej. `https://catalejo-api.onrender.com` |
4. Pulse **Deploy** (2–3 minutos). Al terminar verá la URL pública, por ejemplo `https://catalejo-xxxx.vercel.app`.

> Si cambia `NEXT_PUBLIC_API_BASE_URL` después, debe volver a desplegar (Deployments → ⋯ → **Redeploy**): esa variable se
> fija al construir.

---

## Paso 5 · Conectar frontend y backend (CORS) — 2 min

Por seguridad, el backend solo acepta llamadas desde los sitios autorizados.

1. En Render → servicio **catalejo-api** → **Environment**.
2. Edite `CORS_ORIGINS` y ponga la URL de Vercel **sin `/` al final**:
   ```
   https://catalejo-xxxx.vercel.app
   ```
   Para autorizar varias, sepárelas con coma. (Opcional: para las URL de vista previa de Vercel agregue la variable
   `CORS_ORIGIN_REGEX` con `https://catalejo-.*\.vercel\.app`).
3. **Save Changes**. Render reinicia el servicio solo (1–2 min).

---

## Paso 6 · Verificar que todo funciona — 10 min

Haga esta lista completa antes de compartir el enlace:

1. **Abrir el sitio** `https://catalejo-xxxx.vercel.app`. Si el backend estaba dormido verá el aviso *"Conectando con el
   servidor…"* hasta un minuto. Luego le pedirá el **código de acceso** (si lo configuró).
2. **Caso demo**: *Nueva operación* → **Abrir caso demo**. Debe abrir el expediente con memo, financieros y red flags.
3. **IA activa**: en *Nueva operación*, el Paso 3 debe decir *"Inteligencia artificial: Groq · llama-3.3-70b-versatile"*.
   Si dice *"El servidor no tiene un modelo de IA configurado"*, revise `GROQ_API_KEY` en Render.
4. **Validación de archivos**: suelte un PDF cualquiera en la casilla *Balance de prueba*: debe marcarlo en rojo y explicar
   cómo solucionarlo. El botón *Generar expediente* debe seguir deshabilitado.
5. **Análisis completo con documentos**: para probar sin documentos reales, genere los del caso demo en su computador:
   ```bash
   cd backend
   .venv/Scripts/python scripts/export_demo_documents.py      # crea backend/demo_files/
   ```
   Cargue: el `.xlsx` en la casilla 1, los dos `EEFF_*.pdf` en la 2, el `Certificado_*.pdf` en la 3, y el teaser y el
   avalúo en *Otros archivos*. Pulse **Generar expediente**: verá el avance paso a paso; con Groq tarda unos 2–5 minutos.
   El expediente debe indicar el modo **"LLM en la nube"** y mostrar ajustes de EBITDA propuestos por la IA.
6. **Persistencia**: en Render → **Manual Deploy → Restart service**. Al volver a abrir el sitio, la operación debe seguir en
   *Operaciones* (está guardada en Neon).
7. **Aislamiento**: abra el sitio en una ventana de incógnito. La lista de *Operaciones* debe estar vacía (cada navegador ve
   solo sus operaciones).

---

## Paso 7 · Compartir el enlace

El enlace para los usuarios es la URL de Vercel (`https://catalejo-xxxx.vercel.app`). Mensaje sugerido:

> Hola, te comparto la versión de prueba de **Catalejo Deal Desk**: https://catalejo-xxxx.vercel.app
> Código de acceso: **piloto2026**
> 1. Entra a *Nueva operación* y sube en cada casilla: el balance de prueba (Excel), los estados financieros con notas (PDF) y
>    el certificado de Cámara de Comercio (PDF). Si tienes otros documentos útiles (teaser, avalúos, contratos), súbelos en
>    *Otros archivos*.
> 2. Pulsa *Generar expediente*; el análisis tarda unos minutos.
> 3. Si la página tarda en abrir la primera vez, espera un minuto: el servidor se está iniciando.
> Tus operaciones solo se ven en tu navegador. Cualquier error o comentario, escríbeme.

Puede personalizar el dominio en Vercel (Settings → Domains) gratis si tiene un dominio propio.

---

## Durante las pruebas: qué esperar y cómo resolver problemas

| Situación | Causa | Qué hacer |
|---|---|---|
| La primera carga tarda ~1 min | Render (gratis) duerme tras 15 min sin uso | Normal. Para evitarlo en una sesión de pruebas, abra el sitio 2 min antes. |
| Un paso del análisis se queda quieto 30–60 s | Límite de tokens por minuto de Groq: el sistema espera y reintenta | Normal. Con varios usuarios a la vez, los análisis hacen fila (máximo 2 simultáneos). |
| El expediente dice "Reglas deterministas" en vez de IA | Clave de Groq inválida o cuota diaria agotada (también falló el respaldo) | Revise los *Logs* en Render. La cuota diaria se renueva cada 24 h; puede añadir `OPENROUTER_API_KEY` como respaldo. |
| "No pudimos conectar con el servidor" | Backend caído, URL mal escrita o CORS | Revise `/api/health`, `NEXT_PUBLIC_API_BASE_URL` en Vercel y `CORS_ORIGINS` en Render (sin `/` final). |
| "Código de acceso inválido" | Código distinto al de `ACCESS_CODE` | Verifique el valor en Render → Environment. |
| Un análisis quedó "fallido: el servidor se reinició" | Render reinició el servicio a mitad de un análisis (despliegue o falta de uso) | Vuelva a cargar los documentos. Evite desplegar cambios mientras hay usuarios probando. |
| Se acabaron las 750 h/mes de Render | Muy improbable con un solo servicio | Se renuevan cada mes. |

**Ver qué pasó en un análisis**: en el expediente, botón **Bitácora** (cada paso, llamadas a la IA y notas: contexto enviado,
documentos complementarios descartados por irrelevantes, ajustes que quedaron pendientes, etc.).

**Actualizar la aplicación**: haga `git push` a la rama `main`; Render y Vercel vuelven a desplegar solos.

---

## Variables de entorno (referencia)

**Render (backend)**

| Variable | Obligatoria | Descripción |
|---|---|---|
| `GROQ_API_KEY` | Sí (para IA) | Clave de Groq. Sin ella todo funciona con reglas deterministas, sin IA. |
| `DATABASE_URL` | Sí | Cadena de Neon. Sin ella se usa SQLite temporal y **se pierden los datos** al reiniciar. |
| `CORS_ORIGINS` | Sí | URL(s) de Vercel separadas por coma. |
| `ACCESS_CODE` | Recomendada | Código para entrar. Vacía = acceso libre. |
| `CORS_ORIGIN_REGEX` | No | Expresión regular de orígenes adicionales (vistas previas de Vercel). |
| `LLM_MODEL` | No | Cambiar el modelo, ej. `groq/openai/gpt-oss-120b`. |
| `LLM_FALLBACK_MODELS` | No | Modelos de respaldo separados por coma. |
| `LLM_MAX_INPUT_TOKENS` | No | Tamaño de cada parte de contexto (por defecto 6000 con Groq; se ajusta solo si el proveedor lo rechaza). |
| `MAX_CONCURRENT_JOBS` | No | Análisis simultáneos (2 por defecto). |
| `PYTHON_VERSION`, `STORAGE_DIR` | Ya vienen en `render.yaml` | No las cambie. |

**Vercel (frontend)**

| Variable | Obligatoria | Descripción |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Sí | URL pública del backend en Render, sin `/` final. |

---

## Cambiar de proveedor de IA (opcional)

El backend habla con cualquier API compatible con OpenAI. Basta con poner la clave correspondiente en Render:

| Proveedor | Variable | Modelo por defecto | Nota |
|---|---|---|---|
| Groq (recomendado) | `GROQ_API_KEY` | `llama-3.3-70b-versatile` + respaldo `openai/gpt-oss-120b` | Abierto, gratis, rápido. |
| OpenRouter | `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct:free` | Pocas solicitudes diarias en gratis; útil como respaldo: `LLM_FALLBACK_MODELS=groq/openai/gpt-oss-120b,openrouter/meta-llama/llama-3.3-70b-instruct:free`. |
| Cerebras | `CEREBRAS_API_KEY` | `gpt-oss-120b` | Muy rápido; revise si su plan gratuito sigue vigente. |
| Mistral | `MISTRAL_API_KEY` | `mistral-small-latest` | Modelo abierto; plan gratuito con verificación por teléfono. |
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` | No es abierto y en el plan gratis los datos pueden usarse para entrenar: evítelo con documentos reales. |
| Servidor propio | `LLM_BASE_URL` + `LLM_MODEL` (+ `LLM_API_KEY`) | — | vLLM, LM Studio u Ollama (`/v1`) en un equipo propio. |

Si hay varias claves, se usa la primera en el orden de la tabla, salvo que fije `LLM_MODEL`.

---

## Costos y cuándo pasar a pago

Todo lo anterior cuesta **$0**. Señales de que conviene pagar (cuando el piloto crezca):

- Muchos usuarios a la vez o análisis muy grandes → plan pagado de Groq (se paga por uso, centavos por análisis) para subir los
  límites por minuto.
- No quiere esperar el arranque en frío → Render Starter (~USD 7/mes) mantiene el backend siempre encendido.
- Uso comercial del frontend → Vercel Pro, o Netlify/Render.
