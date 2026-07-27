"""
Enterprise Knowledge Graph entity schemas per docs/002-knowledge-graph.md.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class Specification(BaseModel):
    """PLM/CAD Specification entity."""
    model_config = ConfigDict(populate_by_name=True)

    spec_id: str = Field(..., alias="specId")
    part_number: str = Field(..., alias="partNumber")
    dimension: str = Field(..., description="e.g. Outer Diameter, Bore Depth")
    nominal: float = Field(..., description="Target dimension nominal value (mm/in)")
    tolerance_plus: float = Field(..., alias="tolerancePlus", description="+ tolerance offset")
    tolerance_minus: float = Field(..., alias="toleranceMinus", description="- tolerance offset")
    unit: str = Field(default="mm")
    material: Optional[str] = None
    cad_reference: Optional[str] = Field(default=None, alias="cadReference")


class Supplier(BaseModel):
    """Supplier entity."""
    model_config = ConfigDict(populate_by_name=True)

    supplier_id: str = Field(..., alias="supplierId")
    name: str
    capacity_units_per_week: int = Field(default=1000, alias="capacityUnitsPerWeek")
    region: str = Field(default="North America")
    qualification_status: str = Field(default="APPROVED", alias="qualificationStatus")
    lead_time_days: int = Field(default=3, alias="leadTimeDays")


class Part(BaseModel):
    """Manufacturing Part entity."""
    model_config = ConfigDict(populate_by_name=True)

    part_number: str = Field(..., alias="partNumber")
    name: str
    tolerance_spec_id: Optional[str] = Field(default=None, alias="toleranceSpecId")
    approved_supplier_ids: List[str] = Field(default_factory=list, alias="approvedSupplierIds")
    substitute_part_numbers: List[str] = Field(default_factory=list, alias="substitutePartNumbers")
    in_stock_quantity: int = Field(default=0, alias="inStockQuantity")
    unit_cost_usd: float = Field(default=0.0, alias="unitCostUsd")


class Facility(BaseModel):
    """Factory Facility / Line entity."""
    model_config = ConfigDict(populate_by_name=True)

    facility_id: str = Field(..., alias="facilityId")
    plant_name: str = Field(..., alias="plantName")
    line_id: str = Field(..., alias="lineId")
    cell_id: str = Field(..., alias="cellId")


class Product(BaseModel):
    """Product SKU entity."""
    model_config = ConfigDict(populate_by_name=True)

    sku: str
    revision: str = Field(default="Rev A")
    name: str
    part_numbers: List[str] = Field(default_factory=list, alias="partNumbers")
    facility_id: str = Field(..., alias="facilityId")
    specification_ids: List[str] = Field(default_factory=list, alias="specificationIds")


class Substitution(BaseModel):
    """Part or Supplier substitution rule entity."""
    model_config = ConfigDict(populate_by_name=True)

    substitution_id: str = Field(..., alias="substitutionId")
    source_part_number: str = Field(..., alias="sourcePartNumber")
    target_part_number: str = Field(..., alias="targetPartNumber")
    valid_conditions: Dict[str, Any] = Field(default_factory=dict, alias="validConditions")
    cost_delta_usd: float = Field(default=0.0, alias="costDeltaUsd")
    quality_risk_score: float = Field(default=0.0, alias="qualityRiskScore", description="[0.0 - 1.0]")
    approval_status: str = Field(default="PRE_APPROVED", alias="approvalStatus")


class GraphNode(BaseModel):
    """One entity node in a KnowledgeGraphSnapshot - Knowledge Explorer (/knowledge)."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: str = Field(..., description="PRODUCT | PART | SUPPLIER")
    label: str
    detail: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """One relationship edge in a KnowledgeGraphSnapshot - Knowledge Explorer (/knowledge)."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    target: str
    type: str = Field(..., description="BOM | SUPPLIES | SUBSTITUTE")
    label: Optional[str] = None


class KnowledgeGraphSnapshot(BaseModel):
    """Nodes/edges view of the Knowledge Graph for the Knowledge Explorer screen."""
    model_config = ConfigDict(populate_by_name=True)

    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
