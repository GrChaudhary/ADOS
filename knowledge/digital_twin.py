"""
Digital Twin module implementation (knowledge/digital_twin.py).
Models production line state, active machine parameters, live telemetry, and soft reservations.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict


class MachineParameter(BaseModel):
    """Machine/Tool operating parameter."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    current_value: float = Field(..., alias="currentValue")
    target_nominal: float = Field(..., alias="targetNominal")
    min_limit: float = Field(..., alias="minLimit")
    max_limit: float = Field(..., alias="maxLimit")
    unit: str = Field(default="")
    last_adjusted_at: Optional[str] = Field(default=None, alias="lastAdjustedAt")


class FactoryLineState(BaseModel):
    """Digital Twin state representation for a production line."""
    model_config = ConfigDict(populate_by_name=True)

    line_id: str = Field(..., alias="lineId")
    plant_name: str = Field(..., alias="plantName")
    status: str = Field(default="OPERATIONAL", description="OPERATIONAL | DEGRADED | STOPPED")
    active_product_sku: str = Field(..., alias="activeProductSku")
    current_speed_units_per_hr: int = Field(default=120, alias="currentSpeedUnitsPerHr")
    parameters: Dict[str, MachineParameter] = Field(default_factory=dict)
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    soft_reservations: List[Dict[str, Any]] = Field(default_factory=list, alias="softReservations")


class DigitalTwinStore:
    """
    Digital Twin store managing live line states and tool parameter adjustments.
    """

    def __init__(self):
        self._lines: Dict[str, FactoryLineState] = {}
        self._initialize_seed_lines()

    def _initialize_seed_lines(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()

        line1 = FactoryLineState(
            line_id="Line 1",
            plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
            status="OPERATIONAL",
            active_product_sku="EV-POW-800V",
            current_speed_units_per_hr=150,
            parameters={
                "stator_winding_tension_n": MachineParameter(
                    name="Stator Winding Tension",
                    current_value=42.0,
                    target_nominal=42.0,
                    min_limit=35.0,
                    max_limit=50.0,
                    unit="N"
                )
            },
            telemetry={
                "line_utilization_pct": 94.5,
                "ambient_humidity_pct": 45.0,
                "last_reading_time": now_iso
            }
        )

        line2 = FactoryLineState(
            line_id="Line 2",
            plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
            status="DEGRADED",
            active_product_sku="EV-POW-800V",
            current_speed_units_per_hr=105,
            parameters={
                "cnc101_feed_rate_mm_min": MachineParameter(
                    name="CNC-101 Pre-Roughing Feed Rate",
                    current_value=180.0,
                    target_nominal=200.0,
                    min_limit=150.0,
                    max_limit=250.0,
                    unit="mm/min"
                ),
                "cnc102_spindle_speed_rpm": MachineParameter(
                    name="CNC-102 Precision Finish Spindle Speed",
                    current_value=3450.0,
                    target_nominal=3500.0,
                    min_limit=3000.0,
                    max_limit=4000.0,
                    unit="RPM"
                ),
                "cnc102_tool_offset_z_mm": MachineParameter(
                    name="CNC-102 Tool Z Offset Compensation",
                    current_value=0.045,
                    target_nominal=0.000,
                    min_limit=-0.100,
                    max_limit=0.100,
                    unit="mm"
                )
            },
            telemetry={
                "vibration_rms_mm_s": 4.8,
                "spindle_temp_c": 58.2,
                "ambient_humidity_pct": 78.0,
                "last_reading_time": now_iso
            }
        )

        line3 = FactoryLineState(
            line_id="Line 3",
            plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
            status="OPERATIONAL",
            active_product_sku="EV-POW-800V",
            current_speed_units_per_hr=120,
            parameters={
                "test_bench_load_kw": MachineParameter(
                    name="Final Drive Test Bench Load",
                    current_value=185.0,
                    target_nominal=185.0,
                    min_limit=150.0,
                    max_limit=220.0,
                    unit="kW"
                )
            },
            telemetry={
                "vibration_rms_mm_s": 1.2,
                "spindle_temp_c": 42.0,
                "ambient_humidity_pct": 48.0,
                "last_reading_time": now_iso
            }
        )

        warehouse = FactoryLineState(
            line_id="Warehouse",
            plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
            status="OPERATIONAL",
            active_product_sku="STAGING",
            current_speed_units_per_hr=0,
            parameters={},
            telemetry={
                "staging_capacity_pct": 68.0,
                "ambient_temp_c": 21.5,
                "last_reading_time": now_iso
            }
        )

        self._lines[line1.line_id] = line1
        self._lines[line2.line_id] = line2
        self._lines[line3.line_id] = line3
        self._lines[warehouse.line_id] = warehouse

    def get_line_state(self, line_id: str) -> Optional[FactoryLineState]:
        return self._lines.get(line_id)

    def get_all_line_states(self) -> List[FactoryLineState]:
        return list(self._lines.values())

    def update_parameter(self, line_id: str, parameter_name: str, new_value: float) -> Optional[MachineParameter]:
        line = self._lines.get(line_id)
        if not line or parameter_name not in line.parameters:
            return None

        param = line.parameters[parameter_name]
        param.current_value = new_value
        param.last_adjusted_at = datetime.now(timezone.utc).isoformat()
        return param

    def reserve_line_capacity(self, line_id: str, incident_id: str, units: int, duration_hrs: int) -> bool:
        line = self._lines.get(line_id)
        if not line:
            return False

        line.soft_reservations.append({
            "incident_id": incident_id,
            "units_reserved": units,
            "duration_hrs": duration_hrs,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        return True
