"""
Seed dataset for local development of Enterprise Knowledge Graph and Causal Graph.

Demo company: Nova Motors (see Blueprints/ADOS_Demo_Product_Experience_Blueprint.md).
Single plant (FAC-P1), four lines: Line 1, Line 2, Line 3, Warehouse.
Hero incident narrative: Motor Housing tolerance failure on Line 2 (CNC-101),
resolved via substitution to the high-precision shell sourced from SteelCore
(Supplier B) instead of the default PrecisionCast (Supplier A) batch.

Shared naming scheme (kept in sync with knowledge/asset_model.py and
knowledge/digital_twin.py, owned by the parallel multi-line digital twin
workstream):
    Lines:      Line 1 (FAC-P1-L1), Line 2 (FAC-P1-L2), Line 3 (FAC-P1-L3),
                Warehouse (FAC-P1-WH)
    Machines:   CNC-101 (Line 2), CNC-102 (Line 3), Robot Arm (Line 1),
                Inspection Cell (Line 2), Assembly Line (Line 1)
    Products:   Motor Housing (PROD-100, Line 2), Rotor (PROD-200, Line 3),
                Bearing (PROD-300, Line 3), Cooling Plate (PROD-400, Line 1),
                Gear Assembly (PROD-500, Line 1)
    Suppliers:  PrecisionCast (SUP-201), SteelCore (SUP-202),
                Titan Metals (SUP-203), ForgeWorks (SUP-204),
                Rapid Components (SUP-205)
"""

from .models import Product, Part, Supplier, Facility, Specification, Substitution

# 1. Specifications

SPEC_MH100 = Specification(
    spec_id="SP-100",
    part_number="MH-100",
    dimension="Outer Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.05,
    tolerance_minus=0.05,
    unit="mm",
    material="Aluminum 6061-T6",
    cad_reference="CAD-HOUSING-V3.STEP"
)

SPEC_MH100B = Specification(
    spec_id="SP-100B",
    part_number="MH-100B",
    dimension="Outer Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.03,
    tolerance_minus=0.03,
    unit="mm",
    material="Aluminum 7075-T6",
    cad_reference="CAD-HOUSING-PREMIUM-V1.STEP"
)

SPEC_RT200 = Specification(
    spec_id="SP-200",
    part_number="RT-200",
    dimension="Rotor Core Outer Diameter",
    nominal=62.0,
    tolerance_plus=0.04,
    tolerance_minus=0.04,
    unit="mm",
    material="Silicon Steel M19",
    cad_reference="CAD-ROTOR-CORE-V2.STEP"
)

SPEC_BR300 = Specification(
    spec_id="SP-300",
    part_number="BR-300",
    dimension="Bearing Race Inner Diameter",
    nominal=25.0,
    tolerance_plus=0.02,
    tolerance_minus=0.02,
    unit="mm",
    material="Chrome Steel 52100",
    cad_reference="CAD-BEARING-RACE-V1.STEP"
)

SPEC_CP400 = Specification(
    spec_id="SP-400",
    part_number="CP-400",
    dimension="Cooling Plate Flatness",
    nominal=0.0,
    tolerance_plus=0.10,
    tolerance_minus=0.10,
    unit="mm",
    material="Aluminum 6063",
    cad_reference="CAD-COOLING-PLATE-V1.STEP"
)

SPEC_GR500 = Specification(
    spec_id="SP-500",
    part_number="GR-500",
    dimension="Gear Assembly Housing Bore",
    nominal=38.0,
    tolerance_plus=0.05,
    tolerance_minus=0.05,
    unit="mm",
    material="Steel 4140",
    cad_reference="CAD-GEAR-HOUSING-V2.STEP"
)

# 2. Suppliers

SUPPLIER_PRECISIONCAST = Supplier(
    supplier_id="SUP-201",
    name="PrecisionCast LLC",
    capacity_units_per_week=2500,
    region="Midwest US",
    qualification_status="APPROVED",
    lead_time_days=2
)

SUPPLIER_STEELCORE = Supplier(
    supplier_id="SUP-202",
    name="SteelCore Manufacturing",
    capacity_units_per_week=1200,
    region="West US",
    qualification_status="PRE_QUALIFIED",
    lead_time_days=4
)

SUPPLIER_TITAN_METALS = Supplier(
    supplier_id="SUP-203",
    name="Titan Metals",
    capacity_units_per_week=1800,
    region="Southeast US",
    qualification_status="APPROVED",
    lead_time_days=3
)

SUPPLIER_FORGEWORKS = Supplier(
    supplier_id="SUP-204",
    name="ForgeWorks",
    capacity_units_per_week=1500,
    region="Midwest US",
    qualification_status="APPROVED",
    lead_time_days=3
)

SUPPLIER_RAPID_COMPONENTS = Supplier(
    supplier_id="SUP-205",
    name="Rapid Components",
    capacity_units_per_week=3000,
    region="West US",
    qualification_status="APPROVED",
    lead_time_days=1
)

# 3. Parts

PART_MH100 = Part(
    part_number="MH-100",
    name="Standard Motor Housing Shell",
    tolerance_spec_id="SP-100",
    approved_supplier_ids=["SUP-201"],
    substitute_part_numbers=["MH-100B"],
    in_stock_quantity=450,
    unit_cost_usd=85.50
)

PART_MH100B = Part(
    part_number="MH-100B",
    name="High-Precision Motor Housing Shell",
    tolerance_spec_id="SP-100B",
    approved_supplier_ids=["SUP-201", "SUP-202"],
    substitute_part_numbers=[],
    in_stock_quantity=180,
    unit_cost_usd=98.00
)

PART_RT200 = Part(
    part_number="RT-200",
    name="Rotor Core Assembly",
    tolerance_spec_id="SP-200",
    approved_supplier_ids=["SUP-203"],
    substitute_part_numbers=[],
    in_stock_quantity=320,
    unit_cost_usd=64.00
)

PART_BR300 = Part(
    part_number="BR-300",
    name="Precision Bearing Race",
    tolerance_spec_id="SP-300",
    approved_supplier_ids=["SUP-204"],
    substitute_part_numbers=[],
    in_stock_quantity=900,
    unit_cost_usd=12.75
)

PART_CP400 = Part(
    part_number="CP-400",
    name="Cooling Plate Panel",
    tolerance_spec_id="SP-400",
    approved_supplier_ids=["SUP-205"],
    substitute_part_numbers=[],
    in_stock_quantity=600,
    unit_cost_usd=22.40
)

PART_GR500 = Part(
    part_number="GR-500",
    name="Gear Assembly Housing",
    tolerance_spec_id="SP-500",
    approved_supplier_ids=["SUP-202"],
    substitute_part_numbers=[],
    in_stock_quantity=275,
    unit_cost_usd=54.20
)

# 4. Facilities (one per digital-twin line; Warehouse holds no production cell)

FACILITY_LINE1 = Facility(
    facility_id="FAC-P1-L1",
    plant_name="Nova Motors - Detroit Plant",
    line_id="Line 1",
    cell_id="Cell 1-A (Assembly)"
)

FACILITY_LINE2 = Facility(
    facility_id="FAC-P1-L2",
    plant_name="Nova Motors - Detroit Plant",
    line_id="Line 2",
    cell_id="Cell 2-A (Machining & Fitting)"
)

FACILITY_LINE3 = Facility(
    facility_id="FAC-P1-L3",
    plant_name="Nova Motors - Detroit Plant",
    line_id="Line 3",
    cell_id="Cell 3-A (Machining)"
)

FACILITY_WAREHOUSE = Facility(
    facility_id="FAC-P1-WH",
    plant_name="Nova Motors - Detroit Plant",
    line_id="Warehouse",
    cell_id="Cell WH-1 (Inventory Staging)"
)

# 5. Products

PRODUCT_MOTOR_HOUSING = Product(
    sku="PROD-100",
    revision="Rev C",
    name="Motor Housing",
    part_numbers=["MH-100"],
    facility_id="FAC-P1-L2",
    specification_ids=["SP-100"]
)

PRODUCT_ROTOR = Product(
    sku="PROD-200",
    revision="Rev B",
    name="Rotor",
    part_numbers=["RT-200"],
    facility_id="FAC-P1-L3",
    specification_ids=["SP-200"]
)

PRODUCT_BEARING = Product(
    sku="PROD-300",
    revision="Rev A",
    name="Bearing",
    part_numbers=["BR-300"],
    facility_id="FAC-P1-L3",
    specification_ids=["SP-300"]
)

PRODUCT_COOLING_PLATE = Product(
    sku="PROD-400",
    revision="Rev A",
    name="Cooling Plate",
    part_numbers=["CP-400"],
    facility_id="FAC-P1-L1",
    specification_ids=["SP-400"]
)

PRODUCT_GEAR_ASSEMBLY = Product(
    sku="PROD-500",
    revision="Rev A",
    name="Gear Assembly",
    part_numbers=["GR-500"],
    facility_id="FAC-P1-L1",
    specification_ids=["SP-500"]
)

# 6. Substitutions

SUBSTITUTION_SUB001 = Substitution(
    substitution_id="SUB-001",
    source_part_number="MH-100",
    target_part_number="MH-100B",
    valid_conditions={"line_id": "Line 2", "temperature_max_c": 45},
    cost_delta_usd=12.50,
    quality_risk_score=0.05,
    approval_status="PRE_APPROVED"
)

INITIAL_SPECIFICATIONS = [SPEC_MH100, SPEC_MH100B, SPEC_RT200, SPEC_BR300, SPEC_CP400, SPEC_GR500]
INITIAL_SUPPLIERS = [
    SUPPLIER_PRECISIONCAST, SUPPLIER_STEELCORE, SUPPLIER_TITAN_METALS,
    SUPPLIER_FORGEWORKS, SUPPLIER_RAPID_COMPONENTS
]
INITIAL_PARTS = [PART_MH100, PART_MH100B, PART_RT200, PART_BR300, PART_CP400, PART_GR500]
INITIAL_FACILITIES = [FACILITY_LINE1, FACILITY_LINE2, FACILITY_LINE3, FACILITY_WAREHOUSE]
INITIAL_PRODUCTS = [
    PRODUCT_MOTOR_HOUSING, PRODUCT_ROTOR, PRODUCT_BEARING,
    PRODUCT_COOLING_PLATE, PRODUCT_GEAR_ASSEMBLY
]
INITIAL_SUBSTITUTIONS = [SUBSTITUTION_SUB001]
