"""
Seed dataset for local development of Enterprise Knowledge Graph and Causal Graph.

Demo company: Nova Motors, Plant 04 (Austin, TX) — an EV powertrain assembly
facility producing the 800V High-Performance Electric Drive Unit
(EV-POW-800V), per Blueprints/ADOS_Demo_Product_Experience_Blueprint.md and
documentation/02_Demo_Dataset_and_Digital_Twin.md.

One product (EV-POW-800V), five BOM components, assembled/validated across
four digital-twin lines (Line 1, Line 2, Line 3, Warehouse — see
knowledge/asset_model.py and knowledge/digital_twin.py, owned by the
multi-line digital twin workstream, kept in sync here by naming convention
only, no import coupling).

Hero incident narrative: Motor Housing (MH-8820) bore tolerance breach on
Line 2 (Housing Machining & Inspection, CNC-102 Precision Finish Spindle),
resolved via qualified-supplier switch to the PrecisionCast GmbH variant
(MH-8820-PC) instead of continuing with the incumbent Titan Metals Inc.
batch.

Shared naming scheme:
    Lines:      Line 1 (FAC-P04-L1, Stator & Rotor Cell),
                Line 2 (FAC-P04-L2, Housing Machining & Inspection),
                Line 3 (FAC-P04-L3, Final Drive Testing & Pack Out),
                Warehouse (FAC-P04-WH, Central Warehouse ASRS)
    Machines:   CNC-101 (Pre-Roughing Spindle, Line 2), CNC-102 (Precision
                Finish Spindle, Line 2), ROB-401 (6-Axis Robotic Transfer
                Arm, Line 2), CMM-02 (Automated Laser CMM, Line 2)
    Product:    EV-POW-800V (800V Electric Drive Unit), components:
                Motor Housing (MH-8820), Rotor Shaft (RS-4401), Ceramic
                Bearing (CB-1099), Stator Core (SC-3310), Cooling Plate
                (CP-7700)
    Suppliers:  Titan Metals Inc. (SUP-301), PrecisionCast GmbH (SUP-302),
                Rapid Components (SUP-303), ForgeWorks Ltd (SUP-304),
                SKF Industrial (SUP-305)
"""

from .models import Product, Part, Supplier, Facility, Specification, Substitution

# 1. Specifications

SPEC_MH8820 = Specification(
    spec_id="SP-8820",
    part_number="MH-8820",
    dimension="Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.020,
    tolerance_minus=0.020,
    unit="mm",
    material="Aluminum 6061-T6",
    cad_reference="MH-8820_rev4.step"
)

SPEC_MH8820_PC = Specification(
    spec_id="SP-8820-PC",
    part_number="MH-8820-PC",
    dimension="Housing Bore Diameter",
    nominal=45.0,
    tolerance_plus=0.010,
    tolerance_minus=0.010,
    unit="mm",
    material="Aluminum 6061-T6 (Precision-Machined)",
    cad_reference="MH-8820-PC_rev1.step"
)

SPEC_RS4401 = Specification(
    spec_id="SP-4401",
    part_number="RS-4401",
    dimension="Shaft Runout",
    nominal=0.0,
    tolerance_plus=0.005,
    tolerance_minus=0.005,
    unit="mm",
    material="Forged Steel 4340",
    cad_reference="RS-4401_rev2.step"
)

SPEC_CB1099 = Specification(
    spec_id="SP-1099",
    part_number="CB-1099",
    dimension="Bearing Outer Diameter",
    nominal=25.0,
    tolerance_plus=0.010,
    tolerance_minus=0.010,
    unit="mm",
    material="Silicon Nitride Si3N4 (Grade 5)",
    cad_reference="CB-1099_rev1.step"
)

SPEC_SC3310 = Specification(
    spec_id="SP-3310",
    part_number="SC-3310",
    dimension="Lamination Stack Height",
    nominal=120.0,
    tolerance_plus=0.15,
    tolerance_minus=0.15,
    unit="mm",
    material="Laminate Electrical Steel 0.2mm",
    cad_reference="SC-3310_rev3.step"
)

SPEC_CP7700 = Specification(
    spec_id="SP-7700",
    part_number="CP-7700",
    dimension="Cooling Plate Flatness",
    nominal=0.0,
    tolerance_plus=0.10,
    tolerance_minus=0.10,
    unit="mm",
    material="Vacuum Brazed Aluminum (6 bar)",
    cad_reference="CP-7700_rev1.step"
)

# 2. Suppliers

SUPPLIER_TITAN_METALS = Supplier(
    supplier_id="SUP-301",
    name="Titan Metals Inc.",
    capacity_units_per_week=2000,
    region="Monterrey, Mexico",
    qualification_status="APPROVED",
    lead_time_days=5
)

SUPPLIER_PRECISIONCAST = Supplier(
    supplier_id="SUP-302",
    name="PrecisionCast GmbH",
    capacity_units_per_week=3000,
    region="Austin, TX (Hub Warehouse)",
    qualification_status="APPROVED",
    lead_time_days=1
)

SUPPLIER_RAPID_COMPONENTS = Supplier(
    supplier_id="SUP-303",
    name="Rapid Components",
    capacity_units_per_week=1500,
    region="Round Rock, TX",
    qualification_status="APPROVED",
    lead_time_days=2
)

SUPPLIER_FORGEWORKS = Supplier(
    supplier_id="SUP-304",
    name="ForgeWorks Ltd",
    capacity_units_per_week=1000,
    region="Cleveland, OH",
    qualification_status="APPROVED",
    lead_time_days=7
)

SUPPLIER_SKF_INDUSTRIAL = Supplier(
    supplier_id="SUP-305",
    name="SKF Industrial",
    capacity_units_per_week=500,
    region="Gothenburg, Sweden",
    qualification_status="PRE_QUALIFIED",
    lead_time_days=10
)

# 3. Parts (BOM components of EV-POW-800V)

PART_MH8820 = Part(
    part_number="MH-8820",
    name="Motor Housing",
    tolerance_spec_id="SP-8820",
    approved_supplier_ids=["SUP-301"],
    substitute_part_numbers=["MH-8820-PC"],
    in_stock_quantity=120,
    unit_cost_usd=420.00
)

PART_MH8820_PC = Part(
    part_number="MH-8820-PC",
    name="Motor Housing (PrecisionCast Precision-Machined)",
    tolerance_spec_id="SP-8820-PC",
    approved_supplier_ids=["SUP-301", "SUP-302"],
    substitute_part_numbers=[],
    in_stock_quantity=4500,
    unit_cost_usd=435.00
)

PART_RS4401 = Part(
    part_number="RS-4401",
    name="Rotor Shaft",
    tolerance_spec_id="SP-4401",
    approved_supplier_ids=["SUP-304"],
    substitute_part_numbers=[],
    in_stock_quantity=450,
    unit_cost_usd=310.00
)

PART_CB1099 = Part(
    part_number="CB-1099",
    name="Ceramic Bearing",
    tolerance_spec_id="SP-1099",
    approved_supplier_ids=["SUP-302"],
    substitute_part_numbers=[],
    in_stock_quantity=1200,
    unit_cost_usd=85.00
)

PART_SC3310 = Part(
    part_number="SC-3310",
    name="Stator Core",
    tolerance_spec_id="SP-3310",
    approved_supplier_ids=["SUP-303"],
    substitute_part_numbers=[],
    in_stock_quantity=320,
    unit_cost_usd=540.00
)

PART_CP7700 = Part(
    part_number="CP-7700",
    name="Cooling Plate",
    tolerance_spec_id="SP-7700",
    approved_supplier_ids=["SUP-301"],
    substitute_part_numbers=[],
    in_stock_quantity=600,
    unit_cost_usd=190.00
)

# 4. Facilities (one per digital-twin line; Warehouse holds no production cell)

FACILITY_LINE1 = Facility(
    facility_id="FAC-P04-L1",
    plant_name="Nova Motors - Plant 04 (Austin, TX)",
    line_id="Line 1",
    cell_id="Cell 1-A (Stator & Rotor Cell)"
)

FACILITY_LINE2 = Facility(
    facility_id="FAC-P04-L2",
    plant_name="Nova Motors - Plant 04 (Austin, TX)",
    line_id="Line 2",
    cell_id="Cell 2-A (Housing Machining & Inspection)"
)

FACILITY_LINE3 = Facility(
    facility_id="FAC-P04-L3",
    plant_name="Nova Motors - Plant 04 (Austin, TX)",
    line_id="Line 3",
    cell_id="Cell 3-A (Final Drive Testing & Pack Out)"
)

FACILITY_WAREHOUSE = Facility(
    facility_id="FAC-P04-WH",
    plant_name="Nova Motors - Plant 04 (Austin, TX)",
    line_id="Warehouse",
    cell_id="Cell WH-1 (Central Warehouse ASRS)"
)

# 5. Product (single BOM product spanning all 5 components, validated at
# Line 3 Final Drive Testing & Pack Out)

PRODUCT_EV_POW_800V = Product(
    sku="EV-POW-800V",
    revision="Rev 4",
    name="800V High-Performance Electric Drive Unit",
    part_numbers=["MH-8820", "RS-4401", "CB-1099", "SC-3310", "CP-7700"],
    facility_id="FAC-P04-L3",
    specification_ids=["SP-8820", "SP-4401", "SP-1099", "SP-3310", "SP-7700"]
)

# 6. Substitutions

SUBSTITUTION_SUB001 = Substitution(
    substitution_id="SUB-001",
    source_part_number="MH-8820",
    target_part_number="MH-8820-PC",
    valid_conditions={"line_id": "Line 2", "supplier_preference": "PrecisionCast GmbH"},
    cost_delta_usd=15.00,
    quality_risk_score=0.05,
    approval_status="PRE_APPROVED"
)

INITIAL_SPECIFICATIONS = [SPEC_MH8820, SPEC_MH8820_PC, SPEC_RS4401, SPEC_CB1099, SPEC_SC3310, SPEC_CP7700]
INITIAL_SUPPLIERS = [
    SUPPLIER_TITAN_METALS, SUPPLIER_PRECISIONCAST, SUPPLIER_RAPID_COMPONENTS,
    SUPPLIER_FORGEWORKS, SUPPLIER_SKF_INDUSTRIAL
]
INITIAL_PARTS = [PART_MH8820, PART_MH8820_PC, PART_RS4401, PART_CB1099, PART_SC3310, PART_CP7700]
INITIAL_FACILITIES = [FACILITY_LINE1, FACILITY_LINE2, FACILITY_LINE3, FACILITY_WAREHOUSE]
INITIAL_PRODUCTS = [PRODUCT_EV_POW_800V]
INITIAL_SUBSTITUTIONS = [SUBSTITUTION_SUB001]
