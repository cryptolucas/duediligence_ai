"""Persistencia local (SQLite por defecto, PostgreSQL vía DATABASE_URL) con SQLModel.

Cada operación es una fila independiente (``deal_id``); el expediente completo se guarda como JSON
validado por Pydantic, junto con la bitácora del grafo y el historial del chat.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Text
from sqlmodel import Column, Field, Session, SQLModel, create_engine, select

from app.schemas.deal import DealDossier


class DealRecord(SQLModel, table=True):
    __tablename__ = "deals"

    deal_id: str = Field(primary_key=True)
    company_name: str
    requested_mode: str
    llm_mode: str
    mode_reason: str = ""
    created_at: datetime
    updated_at: datetime
    dossier_json: str = Field(sa_column=Column(Text, nullable=False))
    processing_log_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    chat_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))


class DealJob(SQLModel, table=True):
    """Estado del procesamiento asíncrono de una operación (grafo de agentes en segundo plano)."""

    __tablename__ = "deal_jobs"

    deal_id: str = Field(primary_key=True)
    status: str  # QUEUED | RUNNING | DONE | FAILED
    requested_mode: str
    effective_mode: str
    mode_reason: str = ""
    document_names_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    current_node: Optional[str] = None
    current_message: str = ""
    completed_nodes_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    events_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    llm_calls: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None


MAX_JOB_EVENTS = 60
INTERRUPTED_MESSAGE = "El servidor se reinició mientras se procesaba la operación. Vuelva a cargar los documentos."


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DealRepository:
    """Acceso a deals con una caché en memoria del expediente validado (recálculos < 100 ms)."""

    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)
        self._cache: dict[str, tuple[datetime, DealDossier]] = {}
        self._lock = threading.Lock()

    def create(
        self,
        dossier: DealDossier,
        requested_mode: str,
        mode_reason: str,
        processing_log: list[dict],
    ) -> DealRecord:
        now = _now()
        record = DealRecord(
            deal_id=dossier.deal_id,
            company_name=dossier.company_name,
            requested_mode=requested_mode,
            llm_mode=dossier.llm_mode,
            mode_reason=mode_reason,
            created_at=now,
            updated_at=now,
            dossier_json=dossier.model_dump_json(),
            processing_log_json=json.dumps(processing_log, ensure_ascii=False, default=str),
        )
        with Session(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        with self._lock:
            self._cache[dossier.deal_id] = (record.updated_at, dossier)
        return record

    def get_record(self, deal_id: str) -> Optional[DealRecord]:
        with Session(self.engine) as session:
            return session.get(DealRecord, deal_id)

    def list_records(self) -> list[DealRecord]:
        with Session(self.engine) as session:
            return list(session.exec(select(DealRecord).order_by(DealRecord.updated_at.desc())))

    def load_dossier(self, record: DealRecord) -> DealDossier:
        with self._lock:
            cached = self._cache.get(record.deal_id)
        if cached is not None and cached[0] == record.updated_at:
            return cached[1].model_copy(deep=True)
        dossier = DealDossier.model_validate_json(record.dossier_json)
        with self._lock:
            self._cache[record.deal_id] = (record.updated_at, dossier)
        return dossier.model_copy(deep=True)

    def save_dossier(self, dossier: DealDossier) -> DealRecord:
        with Session(self.engine) as session:
            record = session.get(DealRecord, dossier.deal_id)
            if record is None:
                raise KeyError(dossier.deal_id)
            record.dossier_json = dossier.model_dump_json()
            record.updated_at = _now()
            session.add(record)
            session.commit()
            session.refresh(record)
        with self._lock:
            self._cache[dossier.deal_id] = (record.updated_at, dossier.model_copy(deep=True))
        return record

    # ------------------------------------------------------------------ jobs

    def create_job(
        self, deal_id: str, requested_mode: str, effective_mode: str, mode_reason: str, document_names: list[str]
    ) -> DealJob:
        now = _now()
        job = DealJob(
            deal_id=deal_id,
            status="QUEUED",
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            mode_reason=mode_reason,
            document_names_json=json.dumps(document_names, ensure_ascii=False),
            current_message="En cola",
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as session:
            session.add(job)
            session.commit()
            session.refresh(job)
        return job

    def get_job(self, deal_id: str) -> Optional[DealJob]:
        with Session(self.engine) as session:
            return session.get(DealJob, deal_id)

    def list_jobs(self, statuses: tuple[str, ...] = ("QUEUED", "RUNNING", "FAILED"), limit: int = 20) -> list[DealJob]:
        with Session(self.engine) as session:
            query = select(DealJob).where(DealJob.status.in_(statuses)).order_by(DealJob.created_at.desc()).limit(limit)
            return list(session.exec(query))

    def update_job(self, deal_id: str, *, event: Optional[dict] = None, completed_node: Optional[str] = None, **fields) -> None:
        """Actualiza un job; ``event`` se agrega a la bitácora (últimos MAX_JOB_EVENTS)."""
        with self._lock, Session(self.engine) as session:
            job = session.get(DealJob, deal_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            if completed_node:
                done = json.loads(job.completed_nodes_json)
                if completed_node not in done:
                    done.append(completed_node)
                job.completed_nodes_json = json.dumps(done)
            if event is not None:
                events = json.loads(job.events_json)
                events.append({"at": _now().isoformat(), **event})
                job.events_json = json.dumps(events[-MAX_JOB_EVENTS:], ensure_ascii=False, default=str)
            job.updated_at = _now()
            if fields.get("status") in ("DONE", "FAILED"):
                job.finished_at = job.updated_at
            session.add(job)
            session.commit()

    def fail_interrupted_jobs(self) -> int:
        """Al arrancar: los jobs que quedaron en curso murieron con el proceso anterior."""
        count = 0
        for job in self.list_jobs(("QUEUED", "RUNNING"), limit=1000):
            self.update_job(job.deal_id, status="FAILED", error=INTERRUPTED_MESSAGE, current_message="Interrumpido")
            count += 1
        return count

    def append_chat(self, deal_id: str, entries: list[dict]) -> None:
        with Session(self.engine) as session:
            record = session.get(DealRecord, deal_id)
            if record is None:
                raise KeyError(deal_id)
            history = json.loads(record.chat_json)
            history.extend(entries)
            record.chat_json = json.dumps(history[-200:], ensure_ascii=False, default=str)
            session.add(record)
            session.commit()
