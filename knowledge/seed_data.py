"""
Seed dataset for local development of Enterprise Knowledge Graph and Causal Graph.
Models the MVP demo flow: Line 3, Housing part P-1002, Spec SP-1002, Substitute Part P-1002B, Supplier S-201.
"""

from .models import Product, Part, Supplier, Facility, Specification, Substitution

# 1. Specifications
SPEC_SP1002 = Specification(
    spec_id="SP-1002",
    part_number="P-1002",
    dimension="Outer Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.05,
    tolerance_minus=0.05,
    unit="mm",
    material="Aluminum 6061-T6",
    cad_reference="CAD-HOUSING-V3.STEP"
)

SPEC_SP1002B = Specification(
    spec_id="SP-1002B",
    part_number="P-1002B",
    dimension="Outer Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.03,
    tolerance_minus=0.03,
    unit="mm",
    material="Aluminum 7075-T6",
    cad_reference="CAD-HOUSING-PREMIUM-V1.STEP"
)

# 2. Suppliers
SUPPLIER_S201 = Supplier(
    supplier_id="S-201",
    name="Apex Precision Components Inc.",
    capacity_units_per_week=2500,
    region="Midwest US",
    qualification_status="APPROVED",
    lead_time_days=2
)

SUPPLIER_S202 = Supplier(
    supplier_id="S-202",
    name="Global Tech Machining Corp.",
    capacity_units_per_week=1200,
    region="West US",
    qualification_status="PRE_QUALIFIED",
    lead_time_days=4
)

# 3. Parts
PART_P1002 = Part(
    part_number="P-1002",
    name="Standard Motor Housing Shell",
    tolerance_spec_id="SP-1002",
    approved_supplier_ids=["S-201"],
    substitute_part_numbers=["P-1002B"],
    in_stock_quantity=450,
    unit_cost_usd=85.50
)

PART_P1002B = Part(
    part_number="P-1002B",
    name="High-Precision Motor Housing Shell",
    tolerance_spec_id="SP-1002B",
    approved_supplier_ids=["S-201", "S-202"],
    substitute_part_numbers=[],
    in_stock_quantity=180,
    unit_cost_usd=98.00
)

# 4. Facilities
FACILITY_PLANT1_LINE3 = Facility(
    facility_id="FAC-P1-L3",
    plant_name="Detroit Assembly Plant #1",
    line_id="Line 3",
    cell_id="Cell 3-B (Machining & Fitting)"
)

# 5. Products
PRODUCT_PROD500 = Product(
    sku="PROD-500",
    revision="Rev C",
    name="Industrial Electric Drive Assembly",
    part_numbers=["P-1002"],
    facility_id="FAC-P1-L3",
    specification_ids=["SP-1002"]
)

# 6. Substitutions
SUBSTITUTION_SUB001 = Substitution(
    substitution_id="SUB-001",
    source_part_number="P-1002",
    target_part_number="P-1002B",
    valid_conditions={"line_id": "Line 3", "temperature_max_c": 45},
    cost_delta_usd=12.50,
    quality_risk_score=0.05,
    approval_status="PRE_APPROVED"
)

INITIAL_SPECIFICATIONS = [SPEC_SP1002, SPEC_SP1002B]
INITIAL_SUPPLIERS = [SUPPLIER_S201, SUPPLIER_S202]
INITIAL_PARTS = [PART_P1002, PART_P1002B]
INITIAL_FACILITIES = [FACILITY_PLANT1_LINE3]
INITIAL_PRODUCTS = [PRODUCT_PROD500]
INITIAL_SUBSTITUTIONS = [SUBSTITUTION_SUB001]
