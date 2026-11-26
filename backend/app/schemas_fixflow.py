"""Contracts for the FixFlow maintenance workflow."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SensorReadings(BaseModel):
    temperature_c: float = Field(ge=-40, le=300)
    vibration_mm_s: float = Field(ge=0, le=100)
    pressure_bar: float = Field(default=6.0, ge=0, le=100)
    flow_m3h: float = Field(default=0.0, ge=0, le=5000)


class FixFlowRunRequest(BaseModel):
    equipment_id: str
    readings: SensorReadings
    image_name: str | None = Field(default=None, max_length=255)
    image_size: int | None = Field(default=None, ge=0, le=20_000_000)
    notes: str | None = Field(default=None, max_length=2000)


class VerificationRequest(BaseModel):
    readings: SensorReadings
    notes: str | None = Field(default=None, max_length=2000)


class EquipmentOut(BaseModel):
    id: str
    name: str
    type: str
    manufacturer: str
    model: str
    location: str
    criticality: str
    details: dict[str, Any]
    sensor_readings: dict[str, Any]
    thresholds: dict[str, Any]


class KnowledgeDocOut(BaseModel):
    id: str
    title: str
    source: str
    section: str
    content: str


class FixFlowRunOut(BaseModel):
    id: str
    workflow_execution_id: str
    status: str
    equipment: dict[str, Any]
    readings: dict[str, Any]
    inspection: dict[str, Any]
    diagnosis: dict[str, Any]
    evidence: list[dict[str, Any]]
    safety: dict[str, Any]
    plan: dict[str, Any]
    verification: dict[str, Any] | None = None
    diagnosis_reopened: bool = False
    reopened_diagnosis: dict[str, Any] | None = None
    agents: list[dict[str, Any]]
    created_at: str
    updated_at: str
