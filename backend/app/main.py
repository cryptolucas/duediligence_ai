"""API FastAPI de Catalejo Deal Desk.

Endpoints:
    GET  /api/health                      Estado del servicio.
    GET  /api/llm/status                  Modelos disponibles (cloud / Ollama local).
    GET  /api/benchmarks                  Benchmarks sectoriales por CIIU.
    GET  /api/deals                       Lista de operaciones.
    GET  /api/deals/{deal_id}             Expediente completo + cálculos + memo renderizado.
    POST /api/deals/upload                Procesa documentos (PDF/XLSX/CSV) o inicializa el caso demo.
    POST /api/deals/{deal_id}/recalculate Toggles de ajustes/red flags y recálculo determinista instantáneo.
    POST /api/deals/{deal_id}/chat        Chat con el expediente (fuentes y escenarios).
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from typing import Callable, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.agents.graph import run_deal_pipeline
from app.agents.ingestor import IngestionError
from app.core.config import Settings
from app.db import DealRecord, DealRepository
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    DealSummary,
    DealView,
    LlmStatus,
    ManualAdjustmentInput,
    RecalculateRequest,
    RecalculateResponse,
)
from app.schemas.deal import ANALYST_INPUT_DOCUMENT_ID, DealDossier, EbitdaAdjustment, SourceCitation
from app.services.chat import answer_question
from app.services.citation_guard import verify_quote
from app.services.data_loader import load_benchmarks, load_demo_dossier
from app.services.document_parser import SUPPORTED_EXTENSIONS, UnsupportedDocumentError, parse_document
from app.services.financial_engine import ENGINE_VERSION, apply_adjustment_overrides, recalculate_dossier
from app.services.llm_client import LLMResolution, ollama_models, pick_ollama_model, resolve_llm
from app.services.memo_renderer import render_memo

MAX_FILE_BYTES = 25 * 1024 * 1024
LlmResolver = Callable[[str, Settings], LLMResolution]


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", name or "archivo").strip(" .") or "archivo"
    return base[:120]


def create_app(settings: Optional[Settings] = None, llm_resolver: Optional[LlmResolver] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Catalejo Deal Desk API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.repo = DealRepository(settings.database_url)
    app.state.llm_resolver = llm_resolver or resolve_llm

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
        return {"status": "ok", "version": __version__, "engine_version": ENGINE_VERSION}

    @app.get("/api/llm/status", response_model=LlmStatus)
    def llm_status(request: Request) -> LlmStatus:
        s: Settings = request.app.state.settings
        model = s.cloud_model()
        installed = ollama_models(s.ollama_base_url)
        local_model = pick_ollama_model(s.ollama_model, installed)[0] if installed else None
        return LlmStatus(
            cloud_model=model,
            cloud_available=model is not None,
            ollama_model=local_model.split("/", 1)[1] if local_model else s.ollama_model,
            ollama_base_url=s.ollama_base_url,
            ollama_available=local_model is not None,
            ollama_installed_models=installed or [],
        )

    @app.get("/api/benchmarks")
    def benchmarks() -> dict:
        return load_benchmarks()

    @app.get("/api/deals", response_model=List[DealSummary])
    def list_deals(request: Request) -> List[DealSummary]:
        summaries = []
        benchmarks_data = load_benchmarks()
        for record in repo(request).list_records():
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

    @app.get("/api/deals/{deal_id}", response_model=DealView)
    def get_deal(deal_id: str, request: Request) -> DealView:
        return build_view(request, get_record_or_404(request, deal_id))

    @app.post("/api/deals/upload", response_model=DealView, status_code=201)
    def upload_deal(
        request: Request,
        files: List[UploadFile] = File(default=[]),
        llm_mode: str = Form("CLOUD_API"),
        use_demo: bool = Form(False),
        company_name: Optional[str] = Form(None),
        nit: Optional[str] = Form(None),
        ciiu_code: Optional[str] = Form(None),
    ) -> DealView:
        s: Settings = request.app.state.settings
        benchmarks_data = load_benchmarks()
        started = time.perf_counter()

        if use_demo:
            deal_id = f"demo-{uuid.uuid4().hex[:10]}"
            seed = load_demo_dossier()
            dossier, _, log = run_deal_pipeline(
                deal_id=deal_id, effective_mode="SEED_FALLBACK", benchmarks=benchmarks_data, seed=seed
            )
            reason = "Caso demo precargado (Alimentos y Conservas del Oriente S.A.S.); cifras recalculadas por el motor."
            record = repo(request).create(dossier, "SEED_FALLBACK", reason, log)
            return build_view(request, record)

        if llm_mode not in ("CLOUD_API", "LOCAL_OLLAMA"):
            raise HTTPException(status_code=422, detail="llm_mode debe ser CLOUD_API o LOCAL_OLLAMA.")
        real_files = [f for f in files if f.filename]
        if not real_files:
            raise HTTPException(status_code=422, detail="Cargue al menos un archivo (PDF, XLSX o CSV) o use el caso demo.")

        deal_id = f"deal-{uuid.uuid4().hex[:12]}"
        storage = s.deal_storage(deal_id)
        parsed = []
        try:
            for i, upload in enumerate(real_files, start=1):
                name = _safe_filename(upload.filename or f"archivo_{i}")
                suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if suffix not in SUPPORTED_EXTENSIONS:
                    raise HTTPException(status_code=415, detail=f"Formato no soportado: {name}. Use PDF, XLSX o CSV.")
                target = storage / f"{i:02d}_{name}"
                with target.open("wb") as fh:
                    shutil.copyfileobj(upload.file, fh)
                if target.stat().st_size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail=f"{name} supera el límite de 25 MB.")
                slug = re.sub(r"[^a-z0-9]+", "_", name.lower().rsplit(".", 1)[0]).strip("_")[:40]
                parsed.append(parse_document(target, f"doc_{i:02d}_{slug}", name))
        except UnsupportedDocumentError as exc:
            shutil.rmtree(storage, ignore_errors=True)
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except HTTPException:
            shutil.rmtree(storage, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 - archivo corrupto o ilegible
            shutil.rmtree(storage, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"No se pudo leer un archivo: {type(exc).__name__}: {exc}") from exc

        resolution: LLMResolution = request.app.state.llm_resolver(llm_mode, s)
        hints = {"company_name": company_name, "nit": nit, "ciiu_code": ciiu_code}
        try:
            dossier, _, log = run_deal_pipeline(
                deal_id=deal_id,
                effective_mode=resolution.effective_mode,
                benchmarks=benchmarks_data,
                llm=resolution.client,
                parsed_documents=parsed,
                company_hints={k: v for k, v in hints.items() if v},
            )
        except IngestionError as exc:
            shutil.rmtree(storage, ignore_errors=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        log.insert(
            0,
            {
                "node": "llm_resolution",
                "mode": resolution.effective_mode,
                "duration_ms": 0,
                "llm_calls": 0,
                "message": resolution.reason,
            },
        )
        log.append(
            {
                "node": "pipeline",
                "mode": resolution.effective_mode,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "llm_calls": getattr(resolution.client, "calls", 0),
                "message": f"Expediente generado a partir de {len(parsed)} documento(s).",
            }
        )
        record = repo(request).create(dossier, llm_mode, resolution.reason, log)
        return build_view(request, record)

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
