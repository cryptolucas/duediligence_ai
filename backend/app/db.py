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
