"""API FastAPI de Catalejo Deal Desk.

Endpoints:
    GET  /api/health                      Estado del servicio (y si exige código de acceso).
    GET  /api/llm/status                  Modelos disponibles (cloud gratuito / Ollama local).
    GET  /api/benchmarks                  Benchmarks sectoriales por CIIU.
    GET  /api/upload-requirements         Casillas de carga: documentos obligatorios y «Otros archivos».
    POST /api/documents/validate          Valida un archivo para una casilla (qué está mal y cómo solucionarlo).
    GET  /api/deals                       Lista de operaciones del espacio de trabajo (X-Workspace-Id).
    GET  /api/deals/{deal_id}             Expediente completo + cálculos + memo renderizado.
    POST /api/deals/upload                Caso demo (201, síncrono) o documentos por casilla (202, en segundo plano).
    GET  /api/deals/{deal_id}/status      Progreso del grafo de agentes (nodo actual, llamadas LLM, eventos).
    GET  /api/jobs                        Procesamientos en curso o fallidos.
    POST /api/deals/{deal_id}/recalculate Toggles de ajustes/red flags y recálculo determinista instantáneo.
    POST /api/deals/{deal_id}/chat        Chat con el expediente (fuentes y escenarios).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional

from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.agents.graph import NODE_LABELS, NODE_SEQUENCE, run_deal_pipeline
from app.agents.ingestor import IngestionError, precheck_ingestable
from app.core.config import Settings
from app.db import DealJob, DealRecord, DealRepository
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    DealSummary,
    DealView,
    DocumentValidation,
    JobStatus,
    LlmStatus,
    ManualAdjustmentInput,
    PipelineStep,
    RecalculateRequest,
    RecalculateResponse,
    UploadRequirements,
)
from app.schemas.deal import ANALYST_INPUT_DOCUMENT_ID, DealDossier, EbitdaAdjustment, SourceCitation
from app.services.chat import answer_question
from app.services.citation_guard import verify_quote
from app.services.data_loader import load_benchmarks, load_demo_dossier
from app.services.document_validation import (
    MAX_FILE_MB,
    SLOT_SPECS,
    SPECS_BY_ID,
    assign_slot,
    missing_required,
    validate_file,
)
from app.services.financial_engine import ENGINE_VERSION, apply_adjustment_overrides, recalculate_dossier
from app.services.llm_client import LLMResolution, describe_model, ollama_models, pick_ollama_model, resolve_llm
from app.services.memo_renderer import render_memo

MAX_TOTAL_UPLOAD_MB = 150
LlmResolver = Callable[[str, Settings], LLMResolution]


def _utc(dt: datetime) -> datetime:
    """SQLite devuelve datetimes sin zona: se interpretan como UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", name or "archivo").strip(" .") or "archivo"
    if len(base) > 120:  # conserva la extensión
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 115 - len(ext)] + dot + ext) if dot and len(ext) <= 5 else base[:120]
    return base


def _owner(request: Request) -> str:
    """Espacio de trabajo del navegador (cabecera X-Workspace-Id); vacío si no se envía."""
    return re.sub(r"[^A-Za-z0-9-]", "", request.headers.get("x-workspace-id", ""))[:64]


class AccessCodeMiddleware(BaseHTTPMiddleware):
    """Si ACCESS_CODE está definido, la API exige la cabecera X-Access-Code (salvo /api/health)."""

    def __init__(self, app, code: str):
        super().__init__(app)
        self.code = code

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)
        given = request.headers.get("x-access-code", "")
        if not hmac.compare_digest(given.encode(), self.code.encode()):
            return JSONResponse(status_code=401, content={"detail": "Código de acceso inválido o faltante."})
        return await call_next(request)


def create_app(settings: Optional[Settings] = None, llm_resolver: Optional[LlmResolver] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Catalejo Deal Desk API", version=__version__)
    if settings.access_code:
        app.add_middleware(AccessCodeMiddleware, code=settings.access_code)
    # CORS va por fuera (se agrega al final) para que también las respuestas 401 lleven sus cabeceras.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.repo = DealRepository(settings.database_url)
    app.state.repo.fail_interrupted_jobs()
    app.state.llm_resolver = llm_resolver or resolve_llm
    # Pocos análisis simultáneos: los planes gratuitos de IA limitan tokens por minuto y el servidor es pequeño.
    job_slots = threading.BoundedSemaphore(settings.max_concurrent_jobs)

    # ------------------------------------------------------------------ utilidades

    def repo(request: Request) -> DealRepository:
        return request.app.state.repo

    def get_record_or_404(request: Request, deal_id: str) -> DealRecord:
        record = repo(request).get_record(deal_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Operación {deal_id} no encontrada.")
        return record

    def build_view(request: Request, record: DealRecord) -> DealView:
        dossier = repo(request).load_dossier(record)
        _, result = recalculate_dossier(dossier, load_benchmarks())
        return DealView(
            dossier=dossier,
            financials=result,
            memo_markdown=render_memo(dossier.memo_markdown_template, result),
            processing_log=json.loads(record.processing_log_json),
            requested_mode=record.requested_mode,
            mode_reason=record.mode_reason,
            chat_history=json.loads(record.chat_json),
        )

    # ------------------------------------------------------------------ endpoints

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "engine_version": ENGINE_VERSION,
            "access_code_required": bool(settings.access_code),
        }

    @app.get("/api/llm/status", response_model=LlmStatus)
    def llm_status(request: Request) -> LlmStatus:
        s: Settings = request.app.state.settings
        candidates = s.cloud_candidates()
        model = candidates[0] if candidates else None
        installed = ollama_models(s.ollama_base_url, timeout_s=0.8)
        local_model = pick_ollama_model(s.ollama_model, installed)[0] if installed else None
        return LlmStatus(
            cloud_model=model,
            cloud_available=model is not None,
            cloud_label=describe_model(model) if model else None,
            cloud_fallback_labels=[describe_model(m) for m in candidates[1:]],
            ollama_model=local_model.split("/", 1)[1] if local_model else s.ollama_model,
            ollama_base_url=s.ollama_base_url,
            ollama_available=local_model is not None,
            ollama_installed_models=installed or [],
        )

    @app.get("/api/benchmarks")
    def benchmarks() -> dict:
        return load_benchmarks()

    @app.get("/api/upload-requirements", response_model=UploadRequirements)
    def upload_requirements() -> UploadRequirements:
        return UploadRequirements(slots=list(SLOT_SPECS), max_file_mb=MAX_FILE_MB)

    @app.post("/api/documents/validate", response_model=DocumentValidation)
    def validate_document(file: UploadFile = File(...), slot: str = Form(...)) -> DocumentValidation:
        """Valida un archivo para una casilla sin crear la operación. Siempre 200: el estado va en el cuerpo."""
        if slot not in SPECS_BY_ID:
            raise HTTPException(status_code=422, detail=f"Casilla desconocida: {slot}.")
        name = _safe_filename(file.filename or "archivo")
        with tempfile.TemporaryDirectory(prefix="catalejo_val_") as tmp:
            target = Path(tmp) / name
            with target.open("wb") as fh:
                shutil.copyfileobj(file.file, fh)
            validation, _ = validate_file(target, slot, file.filename or name, "doc_validacion")
        return validation

    @app.get("/api/deals", response_model=List[DealSummary])
    def list_deals(request: Request) -> List[DealSummary]:
        summaries = []
        benchmarks_data = load_benchmarks()
        for record in repo(request).list_records(_owner(request)):
            dossier = repo(request).load_dossier(record)
            _, result = recalculate_dossier(dossier, benchmarks_data)
            last = result.income_statement[-1]
            severities: dict[str, int] = {}
            for flag in dossier.red_flags:
                if flag.status == "ACTIVE":
                    severities[flag.severity] = severities.get(flag.severity, 0) + 1
            summaries.append(
                DealSummary(
                    deal_id=dossier.deal_id,
                    company_name=dossier.company_name,
                    nit=dossier.nit,
                    ciiu_code=dossier.ciiu_code,
                    llm_mode=dossier.llm_mode,
                    requested_mode=record.requested_mode,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    periods=dossier.periods,
                    last_period=last.period,
                    revenue_last_cop=last.revenue.value_cop,
                    ebitda_adjusted_last_cop=last.ebitda_adjusted_cop,
                    all_balances_tie=all(b.balance_check.is_balanced for b in result.balance_sheet),
                    red_flags_by_severity=severities,
                )
            )
        return summaries

    def build_job_status(job: DealJob) -> JobStatus:
        completed = json.loads(job.completed_nodes_json)
        steps = []
        for node, _ in NODE_SEQUENCE:
            if node in completed:
                state = "done"
            elif node == job.current_node and job.status == "FAILED":
                state = "failed"
            elif node == job.current_node and job.status == "RUNNING":
                state = "running"
            else:
                state = "pending"
            steps.append(PipelineStep(node=node, label=NODE_LABELS[node], state=state))
        progress = 100 if job.status == "DONE" else int(len(completed) * 100 / len(NODE_SEQUENCE))
        end = _utc(job.finished_at) if job.finished_at else datetime.now(timezone.utc)
        return JobStatus(
            deal_id=job.deal_id,
            status=job.status,  # type: ignore[arg-type]
            requested_mode=job.requested_mode,
            effective_mode=job.effective_mode,
            mode_reason=job.mode_reason,
            document_names=json.loads(job.document_names_json),
            progress_pct=progress,
            current_node=job.current_node,
            current_message=job.current_message,
            steps=steps,
            events=json.loads(job.events_json),
            llm_calls=job.llm_calls,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
            elapsed_s=round((end - _utc(job.created_at)).total_seconds(), 1),
        )

    def run_job(
        deal_id: str, parsed: list, resolution: LLMResolution, requested_mode: str, hints: dict, storage, owner_id: str = ""
    ) -> None:
        """Ejecuta el grafo en segundo plano (máximo MAX_CONCURRENT_JOBS a la vez) y deja el progreso en deal_jobs."""
        if not job_slots.acquire(blocking=False):
            app.state.repo.update_job(deal_id, current_message="En cola: hay otros análisis en curso; empezará en cuanto termine uno.")
            job_slots.acquire()
        try:
            _run_job(deal_id, parsed, resolution, requested_mode, hints, storage, owner_id)
        finally:
            job_slots.release()

    def _run_job(
        deal_id: str, parsed: list, resolution: LLMResolution, requested_mode: str, hints: dict, storage, owner_id: str
    ) -> None:
        r: DealRepository = app.state.repo
        started = time.perf_counter()
        r.update_job(
            deal_id,
            status="RUNNING",
            current_message="Iniciando el grafo de agentes…",
            event={"type": "info", "message": resolution.reason},
        )

        def on_progress(event: dict) -> None:
            fields: dict = {"current_message": event.get("message", ""), "llm_calls": getattr(resolution.client, "calls", 0)}
            if event["type"] == "node_started":
                fields["current_node"] = event["node"]
            r.update_job(
                deal_id,
                event=event,
                completed_node=event["node"] if event["type"] == "node_finished" else None,
                **fields,
            )

        try:
            dossier, _, log = run_deal_pipeline(
                deal_id=deal_id,
                effective_mode=resolution.effective_mode,
                benchmarks=load_benchmarks(),
                llm=resolution.client,
                parsed_documents=parsed,
                company_hints=hints,
                on_progress=on_progress,
            )
            calls = getattr(resolution.client, "calls", 0)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            log.insert(0, {"node": "llm_resolution", "mode": resolution.effective_mode, "duration_ms": 0, "llm_calls": 0, "message": resolution.reason})
            log.append(
                {
                    "node": "pipeline",
                    "mode": resolution.effective_mode,
                    "duration_ms": elapsed_ms,
                    "llm_calls": calls,
                    "message": f"Expediente generado a partir de {len(parsed)} documento(s).",
                }
            )
            r.create(dossier, requested_mode, resolution.reason, log, owner_id=owner_id)
            # El texto de los documentos ya está en el expediente: los archivos originales no se conservan.
            shutil.rmtree(storage, ignore_errors=True)
            r.update_job(
                deal_id,
                status="DONE",
                current_node=None,
                current_message="Expediente listo",
                llm_calls=calls,
                event={"type": "done", "message": f"Expediente listo en {elapsed_ms / 1000:.1f} s."},
            )
        except Exception as exc:  # noqa: BLE001 - cualquier fallo queda registrado en el job
            message = (
                str(exc)
                if isinstance(exc, IngestionError)
                else f"Ocurrió un error inesperado al procesar los documentos ({type(exc).__name__}: {str(exc)[:300]}). "
                "Intente de nuevo; si se repite, comparta este mensaje con el equipo de Catalejo."
            )
            r.update_job(deal_id, status="FAILED", error=message, current_message="Error", event={"type": "error", "message": message})
            shutil.rmtree(storage, ignore_errors=True)

    @app.get("/api/jobs", response_model=List[JobStatus])
    def list_jobs(request: Request) -> List[JobStatus]:
        return [build_job_status(job) for job in repo(request).list_jobs(owner_id=_owner(request))]

    @app.get("/api/deals/{deal_id}/status", response_model=JobStatus)
    def deal_status(deal_id: str, request: Request) -> JobStatus:
        job = repo(request).get_job(deal_id)
        if job is not None:
            return build_job_status(job)
        record = repo(request).get_record(deal_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Operación {deal_id} no encontrada.")
        # Deals sin job (caso demo): procesados de forma síncrona.
        return JobStatus(
            deal_id=deal_id,
            status="DONE",
            requested_mode=record.requested_mode,
            effective_mode=record.llm_mode,
            mode_reason=record.mode_reason,
            document_names=[],
            progress_pct=100,
            current_node=None,
            current_message="Expediente listo",
            steps=[PipelineStep(node=n, label=NODE_LABELS[n], state="done") for n, _ in NODE_SEQUENCE],
            events=[],
            llm_calls=0,
            error=None,
            created_at=record.created_at,
            updated_at=record.updated_at,
            finished_at=record.created_at,
            elapsed_s=0.0,
        )

    @app.get("/api/deals/{deal_id}", response_model=DealView)
    def get_deal(deal_id: str, request: Request) -> DealView:
        record = repo(request).get_record(deal_id)
        if record is None:
            job = repo(request).get_job(deal_id)
            if job is not None and job.status in ("QUEUED", "RUNNING"):
                raise HTTPException(status_code=409, detail="La operación aún se está procesando.")
            if job is not None and job.status == "FAILED":
                raise HTTPException(status_code=409, detail=f"El procesamiento falló: {job.error}")
            raise HTTPException(status_code=404, detail=f"Operación {deal_id} no encontrada.")
        return build_view(request, record)

    @app.post(
        "/api/deals/upload",
        response_model=None,
        responses={201: {"model": DealView, "description": "Caso demo listo"}, 202: {"model": JobStatus, "description": "Procesamiento en curso"}},
    )
    def upload_deal(
        request: Request,
        background_tasks: BackgroundTasks,
        trial_balance_files: List[UploadFile] = File(default=[]),
        financial_statements_files: List[UploadFile] = File(default=[]),
        chamber_certificate_files: List[UploadFile] = File(default=[]),
        other_files: List[UploadFile] = File(default=[]),
        files: List[UploadFile] = File(default=[], description="Compatibilidad: archivos sin casilla, se clasifican solos."),
        llm_mode: str = Form("CLOUD_API"),
        use_demo: bool = Form(False),
        company_name: Optional[str] = Form(None),
        nit: Optional[str] = Form(None),
        ciiu_code: Optional[str] = Form(None),
    ) -> JSONResponse:
        """Caso demo: síncrono (201 + expediente). Documentos propios: se validan por casilla (3 obligatorios +
        «Otros archivos» opcionales), se parsean de inmediato y el grafo corre en segundo plano (202 + estado)."""
        s: Settings = request.app.state.settings
        owner = _owner(request)

        if use_demo:
            deal_id = f"demo-{uuid.uuid4().hex[:10]}"
            seed = load_demo_dossier()
            dossier, _, log = run_deal_pipeline(
                deal_id=deal_id, effective_mode="SEED_FALLBACK", benchmarks=load_benchmarks(), seed=seed
            )
            reason = "Caso demo precargado (Alimentos y Conservas del Oriente S.A.S.); cifras recalculadas por el motor."
            record = repo(request).create(dossier, "SEED_FALLBACK", reason, log, owner_id=owner)
            return JSONResponse(status_code=201, content=jsonable_encoder(build_view(request, record)))

        if llm_mode not in ("CLOUD_API", "LOCAL_OLLAMA"):
            raise HTTPException(status_code=422, detail="llm_mode debe ser CLOUD_API o LOCAL_OLLAMA.")
        by_slot = {
            "TRIAL_BALANCE": trial_balance_files,
            "FINANCIAL_STATEMENTS": financial_statements_files,
            "CHAMBER_CERTIFICATE": chamber_certificate_files,
            "OTHER": other_files,
        }
        entries: list[tuple[Optional[str], UploadFile]] = [
            (slot, f) for slot, uploads in by_slot.items() for f in uploads if f.filename
        ] + [(None, f) for f in files if f.filename]
        if not entries:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Cargue los documentos obligatorios o abra el caso demo.",
                    "issues": [
                        {"file": None, "slot": spec.id, "message": f"Falta: {spec.label}.", "fix": spec.what_to_upload}
                        for spec in SLOT_SPECS
                        if spec.required
                    ],
                },
            )
        for slot, uploads in by_slot.items():
            spec = SPECS_BY_ID[slot]
            count = sum(1 for f in uploads if f.filename)
            if count > spec.max_files:
                raise HTTPException(status_code=422, detail=f"«{spec.label}» admite máximo {spec.max_files} archivo(s); se enviaron {count}.")

        deal_id = f"deal-{uuid.uuid4().hex[:12]}"
        storage = s.deal_storage(deal_id)
        parsed = []
        issues: list[dict] = []
        valid_slots: list[str] = []
        seen_hashes: dict[str, str] = {}
        total_bytes = 0
        try:
            for i, (slot, upload) in enumerate(entries, start=1):
                original = upload.filename or f"archivo_{i}"
                name = _safe_filename(original)
                target = storage / f"{i:02d}_{name}"
                digest = hashlib.sha256()
                with target.open("wb") as fh:
                    while chunk := upload.file.read(1024 * 1024):
                        digest.update(chunk)
                        fh.write(chunk)
                total_bytes += target.stat().st_size
                if total_bytes > MAX_TOTAL_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"Los archivos suman más de {MAX_TOTAL_UPLOAD_MB} MB. Quite los opcionales más pesados.")
                if digest.hexdigest() in seen_hashes:
                    issues.append(
                        {
                            "file": original,
                            "slot": slot,
                            "message": f"{original} es el mismo archivo que {seen_hashes[digest.hexdigest()]}.",
                            "fix": "Quite el archivo repetido.",
                        }
                    )
                    continue
                seen_hashes[digest.hexdigest()] = original
                slug = re.sub(r"[^a-z0-9]+", "_", name.lower().rsplit(".", 1)[0]).strip("_")[:40]
                validation, doc = validate_file(target, slot, original, f"doc_{i:02d}_{slug}")
                if validation.status == "error" or doc is None:
                    for issue in validation.issues:
                        if issue.level == "error":
                            issues.append({"file": original, "slot": validation.slot, "message": issue.message, "fix": issue.fix})
                    continue
                parsed.append(assign_slot(doc, validation.slot))
                valid_slots.append(validation.slot)
            for spec in missing_required(valid_slots):
                if not any(i["slot"] == spec.id for i in issues):
                    issues.append({"file": None, "slot": spec.id, "message": f"Falta: {spec.label}.", "fix": spec.what_to_upload})
            if issues:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Hay documentos faltantes o con problemas. Corríjalos para iniciar el análisis.",
                        "issues": issues,
                    },
                )
        except HTTPException:
            shutil.rmtree(storage, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 - archivo ilegible no previsto
            shutil.rmtree(storage, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"No se pudo leer un archivo: {type(exc).__name__}: {exc}") from exc

        resolution: LLMResolution = request.app.state.llm_resolver(llm_mode, s)
        problem = precheck_ingestable(parsed, resolution.client is not None)
        if problem:
            shutil.rmtree(storage, ignore_errors=True)
            raise HTTPException(status_code=422, detail=problem)
        hints = {"company_name": company_name, "nit": nit, "ciiu_code": ciiu_code}
        job = repo(request).create_job(
            deal_id,
            llm_mode,
            resolution.effective_mode,
            resolution.reason,
            [p.source.document_name for p in parsed],
            owner_id=owner,
        )
        background_tasks.add_task(
            run_job, deal_id, parsed, resolution, llm_mode, {k: v.strip() for k, v in hints.items() if v and v.strip()}, storage, owner
        )
        return JSONResponse(status_code=202, content=jsonable_encoder(build_job_status(job)))

    def _manual_adjustment(dossier: DealDossier, item: ManualAdjustmentInput) -> EbitdaAdjustment:
        if item.period not in dossier.periods:
            raise HTTPException(status_code=422, detail=f"Periodo {item.period} no existe en el expediente.")
        adj_id = f"adj_manual_{uuid.uuid4().hex[:8]}"
        if item.evidence is not None:
            verified = verify_quote(
                dossier.documents, item.evidence.document_id, item.evidence.page_or_sheet, item.evidence.exact_quote, 0.95
            ).citation
            if verified is None:
                raise HTTPException(
                    status_code=422,
                    detail="La cita del ajuste manual no aparece literalmente en los documentos del deal.",
                )
            citation = verified
        else:
            citation = SourceCitation(
                citation_id=f"cit_{adj_id}",
                document_id=ANALYST_INPUT_DOCUMENT_ID,
                document_name="Nota del analista",
                page_or_sheet="Sandbox de EBITDA",
                cell_or_line_ref=None,
                exact_quote=item.rationale,
                confidence=1.0,
            )
        return EbitdaAdjustment(
            id=adj_id,
            title=item.title,
            category=item.category,
            period=item.period,
            amount_cop=item.amount_cop,
            rationale=item.rationale,
            status=item.status,
            citation=citation,
            origin="ANALYST_MANUAL",
        )

    @app.post("/api/deals/{deal_id}/recalculate", response_model=RecalculateResponse)
    def recalculate(deal_id: str, body: RecalculateRequest, request: Request) -> RecalculateResponse:
        started = time.perf_counter()
        record = get_record_or_404(request, deal_id)
        dossier = repo(request).load_dossier(record)

        adjustments = list(dossier.ebitda_adjustments)
        if body.remove_adjustment_ids:
            by_id = {a.id: a for a in adjustments}
            for adj_id in body.remove_adjustment_ids:
                if adj_id not in by_id:
                    raise HTTPException(status_code=422, detail=f"Ajuste {adj_id} no existe.")
                if by_id[adj_id].origin != "ANALYST_MANUAL":
                    raise HTTPException(status_code=422, detail=f"Solo se pueden eliminar ajustes manuales; {adj_id} se puede rechazar.")
            adjustments = [a for a in adjustments if a.id not in set(body.remove_adjustment_ids)]
        manual = [_manual_adjustment(dossier, item) for item in body.manual_adjustments]
        try:
            adjustments = apply_adjustment_overrides(adjustments, body.adjustment_statuses, manual)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        flag_ids = {f.id for f in dossier.red_flags}
        unknown_flags = set(body.red_flag_statuses) - flag_ids
        if unknown_flags:
            raise HTTPException(status_code=422, detail=f"Red flags inexistentes: {sorted(unknown_flags)}")
        red_flags = [
            f.model_copy(update={"status": body.red_flag_statuses[f.id]}) if f.id in body.red_flag_statuses else f
            for f in dossier.red_flags
        ]
        updated = dossier.model_copy(update={"ebitda_adjustments": adjustments, "red_flags": red_flags})
        _, result = recalculate_dossier(updated, load_benchmarks())
        if body.persist:
            repo(request).save_dossier(DealDossier.model_validate(updated.model_dump()))
        return RecalculateResponse(
            deal_id=deal_id,
            ebitda_adjustments=adjustments,
            red_flags=red_flags,
            financials=result,
            memo_markdown=render_memo(updated.memo_markdown_template, result),
            computation_ms=round((time.perf_counter() - started) * 1000, 2),
            persisted=body.persist,
        )

    @app.post("/api/deals/{deal_id}/chat", response_model=ChatResponse)
    def chat(deal_id: str, body: ChatRequest, request: Request) -> ChatResponse:
        record = get_record_or_404(request, deal_id)
        dossier = repo(request).load_dossier(record)
        benchmarks_data = load_benchmarks()
        _, base = recalculate_dossier(dossier, benchmarks_data)
        llm = None
        if dossier.llm_mode in ("CLOUD_API", "LOCAL_OLLAMA"):
            # Mismo modo que el deal: un deal confidencial (Ollama) nunca se consulta en la nube.
            resolution = request.app.state.llm_resolver(dossier.llm_mode, request.app.state.settings)
            if resolution.effective_mode == dossier.llm_mode:
                llm = resolution.client
        response = answer_question(dossier, base, benchmarks_data, body.message, llm, json.loads(record.chat_json))
        repo(request).append_chat(
            deal_id,
            [
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": response.answer_markdown, "mode": response.mode},
            ],
        )
        return response

    return app


app = create_app()
