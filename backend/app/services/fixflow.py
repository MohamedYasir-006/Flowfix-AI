"""FixFlow AI: deterministic maintenance workflow with optional local LLM diagnosis.

The workflow is intentionally split into deterministic governance steps and an
optional model-assisted diagnosis step:

    equipment -> inspection -> diagnosis -> knowledge -> safety -> plan
              -> supervisor -> verification

Safety, planning, and verification are deterministic. The local LLM may propose
diagnosis hypotheses, but it cannot override a safety decision. Vision output is
explicitly simulated in this MVP and is never treated as a real detection.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError
from ..models import Agent, User, Workflow, WorkflowExecution, utcnow
from ..providers.ollama import OllamaProvider
from ..schemas_fixflow import FixFlowRunRequest, SensorReadings
from ..schemas_llm import ChatMessage, ChatRequest
from ..services import audit as audit_service
from ..services import llm as llm_service
from ..services import provenance as provenance_service

WORKFLOW_NAME = "FixFlow AI - Pump Maintenance"

EQUIPMENT: list[dict[str, Any]] = [
    {
        "id": "pump-p101",
        "name": "Centrifugal Water Pump P-101",
        "type": "Centrifugal process pump",
        "manufacturer": "Grundfos",
        "model": "NK 65-200",
        "location": "Plant A / Cooling Loop",
        "criticality": "HIGH",
        "details": {
            "rated_flow_m3h": 120,
            "rated_head_m": 45,
            "speed_rpm": 2950,
            "installed_year": 2019,
            "service": "Cooling water circulation",
        },
        "sensor_readings": {
            "temperature_c": 84.2,
            "vibration_mm_s": 5.8,
            "pressure_bar": 5.4,
            "flow_m3h": 96.0,
        },
        "thresholds": {
            "temperature_warn_c": 80.0,
            "temperature_block_c": 95.0,
            "vibration_warn_mm_s": 4.5,
            "vibration_block_mm_s": 11.2,
            "pressure_min_bar": 4.0,
            "pressure_max_bar": 8.5,
        },
    },
    {
        "id": "pump-p202",
        "name": "Boiler Feed Pump P-202",
        "type": "Multistage centrifugal pump",
        "manufacturer": "KSB",
        "model": "Movitec VF 40/6",
        "location": "Plant A / Boiler House",
        "criticality": "CRITICAL",
        "details": {
            "rated_flow_m3h": 85,
            "rated_head_m": 120,
            "speed_rpm": 2950,
            "installed_year": 2017,
            "service": "Boiler feedwater",
        },
        "sensor_readings": {
            "temperature_c": 97.6,
            "vibration_mm_s": 12.1,
            "pressure_bar": 5.8,
            "flow_m3h": 78.0,
        },
        "thresholds": {
            "temperature_warn_c": 80.0,
            "temperature_block_c": 95.0,
            "vibration_warn_mm_s": 4.5,
            "vibration_block_mm_s": 11.2,
            "pressure_min_bar": 4.0,
            "pressure_max_bar": 8.5,
        },
    },
    {
        "id": "pump-p303",
        "name": "Transfer Pump P-303",
        "type": "Horizontal end-suction pump",
        "manufacturer": "Sulzer",
        "model": "AHLSTAR WPP 50-200",
        "location": "Plant B / Transfer Station",
        "criticality": "MEDIUM",
        "details": {
            "rated_flow_m3h": 150,
            "rated_head_m": 32,
            "speed_rpm": 1480,
            "installed_year": 2021,
            "service": "Process water transfer",
        },
        "sensor_readings": {
            "temperature_c": 66.8,
            "vibration_mm_s": 2.1,
            "pressure_bar": 6.4,
            "flow_m3h": 118.0,
        },
        "thresholds": {
            "temperature_warn_c": 80.0,
            "temperature_block_c": 95.0,
            "vibration_warn_mm_s": 4.5,
            "vibration_block_mm_s": 11.2,
            "pressure_min_bar": 4.0,
            "pressure_max_bar": 8.5,
        },
    },
]

KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "kb-bearing-vibration",
        "title": "Pump bearing vibration and lubrication guide",
        "source": "FixFlow maintenance handbook",
        "section": "Rotating equipment / Bearings",
        "keywords": [
            "bearing",
            "vibration",
            "misalignment",
            "lubrication",
            "overheating",
            "pump",
        ],
        "content": (
            "Elevated vibration above 4.5 mm/s RMS warrants bearing inspection. "
            "Check grease condition, bearing clearance, coupling alignment, and "
            "foundation bolts. Replace bearings if vibration exceeds 11.2 mm/s or "
            "if heat discoloration is present. Record before/after vibration."
        ),
    },
    {
        "id": "kb-mechanical-seal",
        "title": "Mechanical seal inspection and replacement",
        "source": "OEM seal application guide",
        "section": "Sealing systems",
        "keywords": ["seal", "leak", "seepage", "moisture", "drip", "pump"],
        "content": (
            "Inspect the seal housing for moisture, crystallisation, and flush "
            "line blockage. Do not open a pressurised seal chamber. Replace the "
            "mechanical seal kit if leakage persists after flush restoration. "
            "Verify alignment and run-out before restart."
        ),
    },
    {
        "id": "kb-cavitation",
        "title": "Cavitation, suction starvation, and low-flow diagnosis",
        "source": "Pump system optimisation manual",
        "section": "Hydraulics",
        "keywords": ["cavitation", "suction", "pressure", "flow", "starvation", "pump"],
        "content": (
            "Low suction pressure with reduced flow can indicate a blocked "
            "strainer, closed suction valve, or insufficient NPSH. Inspect the "
            "strainer, verify suction valve position, and confirm available NPSH "
            "before returning the pump to service."
        ),
    },
    {
        "id": "kb-alignment",
        "title": "Shaft alignment and coupling checks",
        "source": "Rotating equipment alignment standard",
        "section": "Alignment",
        "keywords": ["alignment", "coupling", "shaft", "vibration", "misalignment"],
        "content": (
            "Laser-align the pump and motor after bearing or seal work. Check "
            "soft foot, coupling gap, and run-out. Correct alignment to the OEM "
            "tolerance before restart; misalignment is a common vibration cause."
        ),
    },
    {
        "id": "kb-thermal",
        "title": "Bearing and motor temperature limits",
        "source": "Plant reliability standard",
        "section": "Thermal limits",
        "keywords": ["temperature", "thermal", "overheating", "bearing", "motor"],
        "content": (
            "Investigate bearing temperature above 80 C and stop the machine at "
            "95 C unless an approved engineering assessment says otherwise. "
            "Verify lubrication, cooling, and sensor calibration before restart."
        ),
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_equipment(equipment_id: str) -> dict[str, Any]:
    for item in EQUIPMENT:
        if item["id"] == equipment_id:
            return item
    raise NotFoundError(f"Equipment '{equipment_id}' not found")


def list_equipment() -> list[dict[str, Any]]:
    return EQUIPMENT


def list_knowledge() -> list[dict[str, Any]]:
    return KNOWLEDGE


def _severity_rank(value: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(value.upper(), 0)


def _max_severity(*values: str) -> str:
    return max(values, key=_severity_rank) if values else "LOW"


def inspect_image(
    image_name: str | None,
    image_size: int | None,
    notes: str | None,
) -> dict[str, Any]:
    """Return an explicitly simulated inspection result.

    No vision model is invoked in this MVP. The output is labelled as simulated
    and the safety engine ignores it as safety evidence.
    """
    if not image_name:
        return {
            "status": "SKIPPED",
            "simulated": True,
            "model_invoked": False,
            "message": "No image supplied. Vision inspection was not performed.",
            "findings": [],
            "image": None,
            "notes": notes or "",
        }
    return {
        "status": "SIMULATED",
        "simulated": True,
        "model_invoked": False,
        "message": (
            "SIMULATED inspection only. No vision model is available in this MVP. "
            "These findings are illustrative and must not be treated as actual detections."
        ),
        "findings": [
            "SIMULATED visual cue: minor moisture staining near the seal housing.",
            "SIMULATED visual cue: no visible structural cracking in the provided view.",
        ],
        "image": {"name": image_name, "size": image_size or 0},
        "notes": notes or "",
    }


def deterministic_diagnosis(
    equipment: dict[str, Any],
    readings: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    thresholds = equipment["thresholds"]
    temperature = float(readings["temperature_c"])
    vibration = float(readings["vibration_mm_s"])
    pressure = float(readings["pressure_bar"])
    flow = float(readings["flow_m3h"])
    rated_flow = float(equipment["details"].get("rated_flow_m3h") or 0)

    hypotheses: list[dict[str, Any]] = []
    severity = "LOW"

    def add(fault: str, likelihood: float, evidence: list[str], checks: list[str], level: str) -> None:
        nonlocal severity
        hypotheses.append(
            {
                "fault": fault,
                "likelihood": round(likelihood, 2),
                "evidence": evidence,
                "recommended_checks": checks,
                "source": "deterministic",
            }
        )
        severity = _max_severity(severity, level)

    if temperature >= float(thresholds["temperature_block_c"]):
        add(
            "Bearing overheating with possible lubrication failure",
            0.9,
            [f"Temperature {temperature:.1f} C is at or above the block limit"],
            ["Stop the machine", "Check lubrication and cooling", "Inspect bearings"],
            "CRITICAL",
        )
    elif temperature >= float(thresholds["temperature_warn_c"]):
        add(
            "Elevated bearing or motor temperature",
            0.68,
            [f"Temperature {temperature:.1f} C exceeds the warning limit"],
            ["Verify lubrication", "Check cooling airflow", "Calibrate the temperature sensor"],
            "MEDIUM",
        )

    if vibration >= float(thresholds["vibration_block_mm_s"]):
        add(
            "Severe bearing damage or shaft misalignment",
            0.92,
            [f"Vibration {vibration:.1f} mm/s is at or above the block limit"],
            ["Stop the machine", "Inspect bearings and coupling", "Laser-align the shaft"],
            "CRITICAL",
        )
    elif vibration >= float(thresholds["vibration_warn_mm_s"]):
        add(
            "Early bearing wear or misalignment",
            0.64,
            [f"Vibration {vibration:.1f} mm/s exceeds the warning limit"],
            ["Trend vibration", "Inspect bearing condition", "Check alignment"],
            "MEDIUM",
        )

    if pressure < float(thresholds["pressure_min_bar"]):
        add(
            "Suction starvation or cavitation",
            0.7,
            [f"Pressure {pressure:.1f} bar is below the minimum"],
            ["Inspect the suction strainer", "Verify suction valve position", "Check NPSH"],
            "HIGH",
        )
    elif pressure > float(thresholds["pressure_max_bar"]):
        add(
            "Discharge restriction or over-pressure",
            0.55,
            [f"Pressure {pressure:.1f} bar is above the maximum"],
            ["Inspect the discharge line", "Verify valve position", "Check the pressure sensor"],
            "MEDIUM",
        )

    if rated_flow and flow < rated_flow * 0.75:
        add(
            "Flow restriction or impeller wear",
            0.58,
            [f"Flow {flow:.1f} m3/h is below 75% of rated flow ({rated_flow:.0f} m3/h)"],
            ["Inspect the impeller", "Check for blockage", "Verify system demand"],
            "MEDIUM",
        )

    if inspection.get("simulated") and inspection.get("findings"):
        add(
            "Possible seal seepage from a simulated visual cue",
            0.35,
            ["Simulated inspection cue only; this is not a verified detection"],
            ["Physically inspect the seal housing", "Verify flush line pressure"],
            "LOW",
        )

    if not hypotheses:
        add(
            "No significant fault signature",
            0.1,
            ["All supplied readings are within configured thresholds"],
            ["Continue routine condition monitoring"],
            "LOW",
        )

    primary = hypotheses[0]["fault"]
    return {
        "summary": (
            f"{primary}. Severity assessed as {severity} from deterministic "
            "threshold rules."
        ),
        "severity": severity,
        "hypotheses": hypotheses,
        "source": "deterministic",
        "model_invoked": False,
        "deterministic_rules_used": True,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model did not return a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model JSON must be an object")
    return payload


async def _try_llm_diagnosis(
    equipment: dict[str, Any],
    readings: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any] | None:
    """Ask the configured local model for diagnosis hypotheses.

    Any model failure is non-fatal: the caller keeps the deterministic result.
    """
    prompt = json.dumps(
        {
            "task": "industrial pump fault diagnosis",
            "equipment": {
                "name": equipment["name"],
                "type": equipment["type"],
                "service": equipment["details"].get("service"),
                "rated_flow_m3h": equipment["details"].get("rated_flow_m3h"),
            },
            "readings": readings,
            "thresholds": equipment["thresholds"],
            "inspection": inspection,
        },
        ensure_ascii=True,
    )
    system = (
        "You are the FixFlow Fault Diagnosis Agent for industrial water pumps. "
        "Return ONLY a JSON object with keys: summary (string), severity "
        "(LOW|MEDIUM|HIGH|CRITICAL), hypotheses (array of objects with fault, "
        "likelihood 0-1, evidence array, recommended_checks array). "
        "Use only the supplied readings. If inspection is simulated, say so and "
        "do not present it as an actual detection. Do not claim measurements "
        "that were not supplied."
    )
    provider: OllamaProvider = llm_service.get_provider()
    provider.timeout = min(provider.timeout, 20.0)
    response = await llm_service.chat(
        ChatRequest(
            system=system,
            messages=[ChatMessage(role="user", content=prompt)],
            options={"num_ctx": 2048, "temperature": 0.2},
        ),
        provider=provider,
    )
    payload = _extract_json_object(response.message.content)
    severity = str(payload.get("severity", "LOW")).upper()
    if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        severity = "LOW"
    raw_hypotheses = payload.get("hypotheses")
    if not isinstance(raw_hypotheses, list):
        raise ValueError("Model hypotheses must be an array")
    hypotheses: list[dict[str, Any]] = []
    for item in raw_hypotheses[:6]:
        if not isinstance(item, dict):
            continue
        fault = str(item.get("fault") or "").strip()
        if not fault:
            continue
        try:
            likelihood = max(0.0, min(1.0, float(item.get("likelihood", 0.5))))
        except (TypeError, ValueError):
            likelihood = 0.5
        hypotheses.append(
            {
                "fault": fault,
                "likelihood": round(likelihood, 2),
                "evidence": [str(x) for x in (item.get("evidence") or [])][:6],
                "recommended_checks": [
                    str(x) for x in (item.get("recommended_checks") or [])
                ][:6],
                "source": "ollama",
            }
        )
    if not hypotheses:
        raise ValueError("Model returned no usable hypotheses")
    return {
        "summary": str(payload.get("summary") or "Local model diagnosis"),
        "severity": severity,
        "hypotheses": hypotheses,
        "model": response.model,
    }


async def diagnose(
    equipment: dict[str, Any],
    readings: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    deterministic = deterministic_diagnosis(equipment, readings, inspection)
    try:
        model_result = await _try_llm_diagnosis(equipment, readings, inspection)
    except Exception as exc:  # local model is optional; never fail the workflow
        deterministic["llm_error"] = str(exc)[:300]
        deterministic["source"] = "deterministic_fallback"
        return deterministic

    if not model_result:
        deterministic["source"] = "deterministic_fallback"
        return deterministic

    severity = _max_severity(deterministic["severity"], model_result["severity"])
    return {
        "summary": model_result["summary"],
        "severity": severity,
        "hypotheses": [
            *model_result["hypotheses"],
            *deterministic["hypotheses"],
        ],
        "source": "ollama+deterministic",
        "model": model_result["model"],
        "model_invoked": True,
        "deterministic_rules_used": True,
    }


def validate_safety(
    readings: dict[str, Any],
    inspection: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic safety gate. Model output is not accepted as input."""
    thresholds = thresholds or {
        "temperature_warn_c": 80.0,
        "temperature_block_c": 95.0,
        "vibration_warn_mm_s": 4.5,
        "vibration_block_mm_s": 11.2,
        "pressure_min_bar": 4.0,
        "pressure_max_bar": 8.5,
    }
    temperature = float(readings["temperature_c"])
    vibration = float(readings["vibration_mm_s"])
    pressure = float(readings["pressure_bar"])

    decision = "ALLOW"
    rules: list[dict[str, Any]] = []
    reason_codes: list[str] = []

    def escalate(level: str, code: str, detail: str) -> None:
        nonlocal decision
        if level == "BLOCK":
            decision = "BLOCK"
        elif level == "REQUIRE_APPROVAL" and decision != "BLOCK":
            decision = "REQUIRE_APPROVAL"
        if code not in reason_codes:
            reason_codes.append(code)
        rules.append({"rule": code, "result": level, "detail": detail})

    if temperature >= thresholds["temperature_block_c"]:
        escalate(
            "BLOCK",
            "HIGH_TEMPERATURE",
            f"{temperature:.1f} C is at or above the {thresholds['temperature_block_c']:.0f} C block limit",
        )
    elif temperature >= thresholds["temperature_warn_c"]:
        escalate(
            "REQUIRE_APPROVAL",
            "TEMPERATURE_ELEVATED",
            f"{temperature:.1f} C exceeds the {thresholds['temperature_warn_c']:.0f} C warning limit",
        )

    if vibration >= thresholds["vibration_block_mm_s"]:
        escalate(
            "BLOCK",
            "HIGH_VIBRATION",
            f"{vibration:.1f} mm/s is at or above the {thresholds['vibration_block_mm_s']:.1f} mm/s block limit",
        )
    elif vibration >= thresholds["vibration_warn_mm_s"]:
        escalate(
            "REQUIRE_APPROVAL",
            "VIBRATION_ELEVATED",
            f"{vibration:.1f} mm/s exceeds the {thresholds['vibration_warn_mm_s']:.1f} mm/s warning limit",
        )

    if pressure < thresholds["pressure_min_bar"]:
        escalate(
            "REQUIRE_APPROVAL",
            "LOW_PRESSURE",
            f"{pressure:.1f} bar is below the {thresholds['pressure_min_bar']:.1f} bar minimum",
        )
    elif pressure > thresholds["pressure_max_bar"]:
        escalate(
            "REQUIRE_APPROVAL",
            "HIGH_PRESSURE",
            f"{pressure:.1f} bar is above the {thresholds['pressure_max_bar']:.1f} bar maximum",
        )

    if inspection.get("simulated"):
        rules.append(
            {
                "rule": "SIMULATED_INSPECTION_NOT_SAFETY_EVIDENCE",
                "result": "IGNORED",
                "detail": "Simulated visual output is excluded from the safety decision.",
            }
        )
        reason_codes.append("SIMULATED_INSPECTION_IGNORED")

    if not reason_codes:
        reason_codes = ["SAFETY_LIMITS_WITHIN_RANGE"]

    return {
        "decision": decision,
        "deterministic": True,
        "llm_can_override": False,
        "reason_codes": reason_codes,
        "rules": rules,
        "inputs_used": ["temperature_c", "vibration_mm_s", "pressure_bar"],
        "inspection_used": False,
        "evaluated_at": _now(),
    }


def retrieve_knowledge(query: str, limit: int = 3) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored: list[tuple[int, dict[str, Any]]] = []
    for doc in KNOWLEDGE:
        score = len(tokens.intersection(set(doc["keywords"])))
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1]["title"]))
    selected = [doc for _, doc in scored[:limit]]
    if not selected:
        selected = [KNOWLEDGE[0], KNOWLEDGE[2]]
    return [
        {
            "id": doc["id"],
            "title": doc["title"],
            "source": doc["source"],
            "section": doc["section"],
            "content": doc["content"],
            "score": next((s for s, d in scored if d["id"] == doc["id"]), 0),
        }
        for doc in selected
    ]


def build_plan(
    equipment: dict[str, Any],
    diagnosis: dict[str, Any],
    evidence: list[dict[str, Any]],
    safety: dict[str, Any],
) -> dict[str, Any]:
    fault_text = " ".join(h["fault"] for h in diagnosis.get("hypotheses", [])).lower()
    tasks: list[dict[str, Any]] = []

    def add_task(
        title: str,
        priority: str,
        tools: list[str],
        parts: list[str],
        hours: float,
        procedure: list[str],
        acceptance: list[str],
    ) -> None:
        tasks.append(
            {
                "id": f"T{len(tasks) + 1}",
                "title": title,
                "priority": priority,
                "tools": tools,
                "parts": parts,
                "estimated_hours": hours,
                "procedure": procedure,
                "acceptance": acceptance,
            }
        )

    if "bearing" in fault_text or "vibration" in fault_text or "alignment" in fault_text:
        add_task(
            "Inspect bearings and correct shaft alignment",
            "HIGH",
            ["vibration analyzer", "laser alignment tool", "bearing puller", "torque wrench"],
            ["Bearing set 6308-2Z", "High-temperature grease"],
            4.0,
            [
                "Lock out and tag out the pump.",
                "Measure vibration and bearing temperature.",
                "Inspect bearing condition and grease.",
                "Replace bearings if damaged; otherwise re-grease.",
                "Laser-align pump and motor; check soft foot.",
            ],
            ["Vibration below 4.5 mm/s RMS", "Bearing temperature below 80 C"],
        )

    if "seal" in fault_text or "leak" in fault_text or "seepage" in fault_text:
        add_task(
            "Inspect and restore the mechanical seal",
            "MEDIUM",
            ["seal removal kit", "torque wrench", "flush line gauge"],
            ["Mechanical seal kit", "Seal O-ring set"],
            3.0,
            [
                "Depressurise and drain the seal chamber.",
                "Inspect seal faces, O-rings, and flush line.",
                "Replace the seal kit if leakage or damage is found.",
                "Restore flush flow and check for leaks.",
            ],
            ["No visible leakage after restart", "Flush pressure within OEM range"],
        )

    if "cavitation" in fault_text or "suction" in fault_text or "flow" in fault_text:
        add_task(
            "Clear suction restriction and verify NPSH",
            "HIGH",
            ["strainer brush", "pressure gauge", "valve wrench"],
            ["Suction strainer element"],
            2.0,
            [
                "Verify suction valve is fully open.",
                "Inspect and clean the suction strainer.",
                "Measure available NPSH and compare with the pump curve.",
                "Confirm flow returns to the operating range.",
            ],
            ["Flow at least 75% of rated flow", "Suction pressure above minimum"],
        )

    if not tasks:
        add_task(
            "Perform routine pump condition inspection",
            "LOW",
            ["vibration analyzer", "temperature probe"],
            ["Grease cartridge"],
            1.5,
            [
                "Record baseline readings.",
                "Inspect for leaks, noise, and loose fasteners.",
                "Lubricate according to the maintenance schedule.",
            ],
            ["Readings remain within warning limits"],
        )

    add_task(
        "Run post-maintenance verification",
        "HIGH",
        ["vibration analyzer", "temperature probe", "pressure gauge", "flow meter"],
        [],
        1.0,
        [
            "Restart under supervision.",
            "Record temperature, vibration, pressure, and flow.",
            "Submit readings to FixFlow verification.",
        ],
        ["Verification result is PASS"],
    )

    tools = sorted({tool for task in tasks for tool in task["tools"]})
    parts = sorted({part for task in tasks for part in task["parts"]})
    downtime = round(sum(task["estimated_hours"] for task in tasks[:-1]), 1)
    gate = safety["decision"]
    note = (
        "Work is blocked until the safety condition is cleared and re-assessed."
        if gate == "BLOCK"
        else "Supervisor approval is required before work starts."
        if gate == "REQUIRE_APPROVAL"
        else "Work may proceed under the standard permit-to-work process."
    )
    return {
        "tasks": tasks,
        "required_tools": tools,
        "required_parts": parts,
        "estimated_downtime_hours": downtime,
        "safety_gate": gate,
        "gate_note": note,
        "evidence_ids": [doc["id"] for doc in evidence],
        "equipment_id": equipment["id"],
        "created_at": _now(),
    }


def verify_maintenance(
    equipment: dict[str, Any],
    readings: dict[str, Any],
    notes: str | None = None,
) -> dict[str, Any]:
    thresholds = equipment["thresholds"]
    temperature = float(readings["temperature_c"])
    vibration = float(readings["vibration_mm_s"])
    pressure = float(readings["pressure_bar"])
    flow = float(readings["flow_m3h"])
    rated_flow = float(equipment["details"].get("rated_flow_m3h") or 0)
    minimum_flow = rated_flow * 0.75 if rated_flow else 0.0

    checks = [
        {
            "name": "Temperature",
            "value": temperature,
            "unit": "C",
            "limit": f"< {thresholds['temperature_warn_c']:.0f}",
            "passed": temperature < float(thresholds["temperature_warn_c"]),
        },
        {
            "name": "Vibration",
            "value": vibration,
            "unit": "mm/s",
            "limit": f"< {thresholds['vibration_warn_mm_s']:.1f}",
            "passed": vibration < float(thresholds["vibration_warn_mm_s"]),
        },
        {
            "name": "Pressure",
            "value": pressure,
            "unit": "bar",
            "limit": f"{thresholds['pressure_min_bar']:.1f}-{thresholds['pressure_max_bar']:.1f}",
            "passed": float(thresholds["pressure_min_bar"])
            <= pressure
            <= float(thresholds["pressure_max_bar"]),
        },
        {
            "name": "Flow",
            "value": flow,
            "unit": "m3/h",
            "limit": f">= {minimum_flow:.0f}",
            "passed": flow >= minimum_flow,
        },
    ]
    result = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    return {
        "result": result,
        "checks": checks,
        "notes": notes or "",
        "verified_at": _now(),
        "diagnosis_reopened": result == "FAIL",
    }


def _ensure_workflow(db: Session, org_id: str) -> Workflow:
    workflow = db.execute(
        select(Workflow).where(
            Workflow.org_id == org_id,
            Workflow.name == WORKFLOW_NAME,
        )
    ).scalar_one_or_none()
    if workflow is not None:
        return workflow
    workflow = Workflow(
        org_id=org_id,
        name=WORKFLOW_NAME,
        description="Vision-assisted pump maintenance with deterministic safety gating.",
        status="ACTIVE",
        metadata_json={"fixflow": True, "version": "mvp"},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(workflow)
    db.flush()
    return workflow


def _ensure_agent(db: Session, org_id: str, user_id: str, agent_id: str, name: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is not None and agent.org_id == org_id:
        return agent
    agent = db.execute(select(Agent).where(Agent.name == name)).scalar_one_or_none()
    if agent is not None:
        return agent
    agent = Agent(
        id=agent_id,
        org_id=org_id,
        name=name,
        owner_user_id=user_id,
        environment="dev",
        status="ACTIVE",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(agent)
    db.flush()
    return agent


def _ensure_agents(
    db: Session, org_id: str, user_id: str
) -> dict[str, Agent]:
    specs = {
        "vision": ("fixflow-vision-agent", "FixFlow Vision Agent"),
        "diagnosis": ("fixflow-diagnosis-agent", "FixFlow Diagnosis Agent"),
        "knowledge": ("fixflow-knowledge-agent", "FixFlow Knowledge Agent"),
        "safety": ("fixflow-safety-agent", "FixFlow Safety Agent"),
        "planning": ("fixflow-planning-agent", "FixFlow Planning Agent"),
        "verification": ("fixflow-verification-agent", "FixFlow Verification Agent"),
        "supervisor": ("fixflow-supervisor-agent", "FixFlow Supervisor Agent"),
    }
    return {
        key: _ensure_agent(db, org_id, user_id, agent_id, name)
        for key, (agent_id, name) in specs.items()
    }


def _record_artifact(
    db: Session,
    *,
    execution: WorkflowExecution,
    producer: Agent,
    artifact_type: str,
    name: str,
    content: dict[str, Any],
    parent_artifact_ids: list[str] | None = None,
) -> str:
    artifact = provenance_service.record_artifact(
        db,
        org_id=execution.org_id,
        producer=producer,
        artifact_type=artifact_type,
        name=name,
        content=content,
        workflow_execution_id=execution.id,
        parent_artifact_ids=parent_artifact_ids or [],
        trust_metadata={"fixflow": True, "simulated": bool(content.get("simulated"))},
    )
    return artifact.id


def _agent_row(
    *,
    agent: Agent,
    role: str,
    status: str,
    summary: str,
    artifact_id: str | None,
    started_at: str,
    ended_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": role,
        "status": status,
        "summary": summary,
        "artifact_id": artifact_id,
        "started_at": started_at,
        "ended_at": ended_at if ended_at is not None else (None if status == "PENDING" else _now()),
    }


async def start_run(
    db: Session,
    *,
    org_id: str,
    user: User,
    request: FixFlowRunRequest,
) -> dict[str, Any]:
    equipment = get_equipment(request.equipment_id)
    readings = request.readings.model_dump()
    workflow = _ensure_workflow(db, org_id)
    agents = _ensure_agents(db, org_id, user.id)
    started = _now()
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=org_id,
        external_key=equipment["id"],
        status="RUNNING",
        started_at=started,
        metadata_json={},
    )
    db.add(execution)
    db.flush()

    agent_rows: list[dict[str, Any]] = []

    snapshot = {
        "equipment": equipment,
        "readings": readings,
        "captured_at": started,
    }
    snapshot_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["supervisor"],
        artifact_type="equipment_snapshot",
        name="Equipment and sensor snapshot",
        content=snapshot,
    )
    inspection = inspect_image(request.image_name, request.image_size, request.notes)
    inspection_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["vision"],
        artifact_type="vision_inspection",
        name="Simulated visual inspection",
        content=inspection,
        parent_artifact_ids=[snapshot_id],
    )
    agent_rows.append(
        _agent_row(
            agent=agents["vision"],
            role="vision",
            status="SIMULATED" if inspection["status"] == "SIMULATED" else "SKIPPED",
            summary=inspection["message"],
            artifact_id=inspection_id,
            started_at=started,
        )
    )

    diagnosis = await diagnose(equipment, readings, inspection)
    diagnosis_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["diagnosis"],
        artifact_type="fault_diagnosis",
        name="Fault diagnosis",
        content=diagnosis,
        parent_artifact_ids=[snapshot_id, inspection_id],
    )
    agent_rows.append(
        _agent_row(
            agent=agents["diagnosis"],
            role="diagnosis",
            status="COMPLETED",
            summary=diagnosis["summary"],
            artifact_id=diagnosis_id,
            started_at=started,
        )
    )

    query = " ".join(
        [
            equipment["name"],
            equipment["details"].get("service", ""),
            diagnosis["summary"],
            *[item["fault"] for item in diagnosis["hypotheses"]],
        ]
    )
    evidence = retrieve_knowledge(query)
    evidence_content = {"query": query, "documents": evidence, "retrieved_at": _now()}
    evidence_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["knowledge"],
        artifact_type="knowledge_evidence",
        name="Retrieved maintenance evidence",
        content=evidence_content,
        parent_artifact_ids=[diagnosis_id],
    )
    agent_rows.append(
        _agent_row(
            agent=agents["knowledge"],
            role="knowledge",
            status="COMPLETED",
            summary=f"Retrieved {len(evidence)} maintenance references.",
            artifact_id=evidence_id,
            started_at=started,
        )
    )

    safety = validate_safety(readings, inspection, equipment["thresholds"])
    safety_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["safety"],
        artifact_type="safety_validation",
        name="Deterministic safety validation",
        content=safety,
        parent_artifact_ids=[snapshot_id, diagnosis_id],
    )
    audit_service.record_event(
        db,
        event_type="decision",
        action_id=execution.id,
        agent_id=agents["safety"].id,
        decision={
            "ALLOW": "ALLOW",
            "REQUIRE_APPROVAL": "REQUIRE_APPROVAL",
            "BLOCK": "DENY",
        }[safety["decision"]],
        risk_level="HIGH" if safety["decision"] == "BLOCK" else "MEDIUM",
        reason_codes=safety["reason_codes"],
        metadata={
            "fixflow": True,
            "workflowExecutionId": execution.id,
            "equipmentId": equipment["id"],
            "safetyDecision": safety["decision"],
        },
        org_id=org_id,
    )
    agent_rows.append(
        _agent_row(
            agent=agents["safety"],
            role="safety",
            status="COMPLETED" if safety["decision"] != "BLOCK" else "BLOCKED",
            summary=f"Deterministic safety decision: {safety['decision']}.",
            artifact_id=safety_id,
            started_at=started,
        )
    )

    plan = build_plan(equipment, diagnosis, evidence, safety)
    plan_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["planning"],
        artifact_type="maintenance_plan",
        name="Maintenance plan",
        content=plan,
        parent_artifact_ids=[diagnosis_id, evidence_id, safety_id],
    )
    agent_rows.append(
        _agent_row(
            agent=agents["planning"],
            role="planning",
            status="COMPLETED",
            summary=(
                f"{len(plan['tasks'])} tasks, {plan['estimated_downtime_hours']} h "
                f"estimated downtime, gate {plan['safety_gate']}."
            ),
            artifact_id=plan_id,
            started_at=started,
        )
    )

    run_status = {
        "ALLOW": "AWAITING_VERIFICATION",
        "REQUIRE_APPROVAL": "AWAITING_APPROVAL",
        "BLOCK": "BLOCKED",
    }[safety["decision"]]

    supervisor_summary = {
        "status": run_status,
        "equipment_id": equipment["id"],
        "safety_decision": safety["decision"],
        "diagnosis_severity": diagnosis["severity"],
        "artifact_ids": [
            snapshot_id,
            inspection_id,
            diagnosis_id,
            evidence_id,
            safety_id,
            plan_id,
        ],
        "completed_at": _now(),
    }
    supervisor_id = _record_artifact(
        db,
        execution=execution,
        producer=agents["supervisor"],
        artifact_type="supervisor_summary",
        name="Supervisor run summary",
        content=supervisor_summary,
        parent_artifact_ids=[
            snapshot_id,
            inspection_id,
            diagnosis_id,
            evidence_id,
            safety_id,
            plan_id,
        ],
    )
    agent_rows.append(
        _agent_row(
            agent=agents["supervisor"],
            role="supervisor",
            status="COMPLETED" if run_status != "BLOCKED" else "BLOCKED",
            summary=f"Workflow status: {run_status}.",
            artifact_id=supervisor_id,
            started_at=started,
        )
    )
    agent_rows.append(
        _agent_row(
            agent=agents["verification"],
            role="verification",
            status="PENDING",
            summary="Waiting for post-maintenance readings.",
            artifact_id=None,
            started_at=started,
            ended_at=None,
        )
    )

    run = {
        "id": execution.id,
        "workflow_execution_id": execution.id,
        "status": run_status,
        "equipment": equipment,
        "readings": readings,
        "inspection": {**inspection, "artifact_id": inspection_id},
        "diagnosis": {**diagnosis, "artifact_id": diagnosis_id},
        "evidence": evidence,
        "safety": {**safety, "artifact_id": safety_id},
        "plan": {**plan, "artifact_id": plan_id},
        "verification": None,
        "diagnosis_reopened": False,
        "reopened_diagnosis": None,
        "agents": agent_rows,
        "created_at": started,
        "updated_at": _now(),
    }
    execution.metadata_json = run
    db.commit()
    return run


def get_run(db: Session, org_id: str, run_id: str) -> dict[str, Any]:
    execution = db.get(WorkflowExecution, run_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("FixFlow run not found")
    run = execution.metadata_json
    if not isinstance(run, dict) or run.get("workflow_execution_id") != execution.id:
        raise NotFoundError("FixFlow run not found")
    return run


def list_runs(db: Session, org_id: str, limit: int = 20) -> list[dict[str, Any]]:
    executions = db.execute(
        select(WorkflowExecution)
        .where(WorkflowExecution.org_id == org_id)
        .order_by(WorkflowExecution.started_at.desc())
        .limit(limit)
    ).scalars().all()
    runs: list[dict[str, Any]] = []
    for execution in executions:
        run = execution.metadata_json
        if isinstance(run, dict) and run.get("workflow_execution_id") == execution.id:
            runs.append(run)
    return runs


def verify_run(
    db: Session,
    *,
    org_id: str,
    user: User,
    run_id: str,
    readings: SensorReadings,
    notes: str | None = None,
) -> dict[str, Any]:
    execution = db.get(WorkflowExecution, run_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("FixFlow run not found")
    current = execution.metadata_json
    if not isinstance(current, dict) or current.get("workflow_execution_id") != execution.id:
        raise NotFoundError("FixFlow run not found")
    if (current.get("verification") or {}).get("result") == "PASS":
        raise ConflictError("FixFlow run is already verified")
    if execution.status in ("COMPLETED", "FAILED"):
        raise ConflictError("FixFlow run is already closed")

    equipment = get_equipment(current["equipment"]["id"])
    post_readings = readings.model_dump()
    verification = verify_maintenance(equipment, post_readings, notes)
    verification_id = _record_artifact(
        db,
        execution=execution,
        producer=_ensure_agents(db, org_id, user.id)["verification"],
        artifact_type="maintenance_verification",
        name="Post-maintenance verification",
        content={**verification, "readings": post_readings},
        parent_artifact_ids=[
            current["plan"]["artifact_id"],
            current["diagnosis"]["artifact_id"],
            current["inspection"]["artifact_id"],
        ],
    )
    verification["artifact_id"] = verification_id

    run = dict(current)
    run["verification"] = verification
    run["updated_at"] = _now()

    agents = [dict(item) for item in run["agents"]]
    for item in agents:
        if item["role"] == "verification":
            item["status"] = "COMPLETED" if verification["result"] == "PASS" else "FAILED"
            item["summary"] = (
                "Post-maintenance verification passed."
                if verification["result"] == "PASS"
                else "Post-maintenance verification failed; diagnosis reopened."
            )
            item["artifact_id"] = verification_id
            item["ended_at"] = _now()
    run["agents"] = agents

    if verification["result"] == "FAIL":
        reopened = deterministic_diagnosis(equipment, post_readings, run["inspection"])
        reopened["summary"] = (
            "Diagnosis reopened after failed verification. " + reopened["summary"]
        )
        reopened["reopened_at"] = _now()
        reopened_id = _record_artifact(
            db,
            execution=execution,
            producer=_ensure_agents(db, org_id, user.id)["diagnosis"],
            artifact_type="reopened_diagnosis",
            name="Reopened fault diagnosis",
            content=reopened,
            parent_artifact_ids=[verification_id, current["diagnosis"]["artifact_id"]],
        )
        run["diagnosis_reopened"] = True
        run["reopened_diagnosis"] = {**reopened, "artifact_id": reopened_id}
        run["status"] = "VERIFICATION_FAILED"
        execution.status = "FAILED"
        decision = "DENY"
        reason_codes = ["FIXFLOW_VERIFICATION_FAILED", "DIAGNOSIS_REOPENED"]
    else:
        run["diagnosis_reopened"] = False
        run["reopened_diagnosis"] = None
        run["status"] = "VERIFIED"
        execution.status = "COMPLETED"
        decision = "ALLOW"
        reason_codes = ["FIXFLOW_VERIFICATION_PASSED"]

    execution.ended_at = _now()
    execution.metadata_json = run
    audit_service.record_event(
        db,
        event_type="workflow",
        action_id=execution.id,
        decision=decision,
        risk_level="LOW" if verification["result"] == "PASS" else "HIGH",
        reason_codes=reason_codes,
        metadata={
            "fixflow": True,
            "workflowExecutionId": execution.id,
            "equipmentId": equipment["id"],
            "verificationResult": verification["result"],
        },
        org_id=org_id,
    )
    db.commit()
    return run
