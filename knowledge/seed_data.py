"""
Seed dataset for local development of Enterprise Knowledge Graph and Causal Graph.

Demo company: Nova Motors, Plant 04 (Bangalore, Karnataka) — an EV powertrain assembly
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
    region="Bangalore, Karnataka (Hub Warehouse)",
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
    plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
    line_id="Line 1",
    cell_id="Cell 1-A (Stator & Rotor Cell)"
)

FACILITY_LINE2 = Facility(
    facility_id="FAC-P04-L2",
    plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
    line_id="Line 2",
    cell_id="Cell 2-A (Housing Machining & Inspection)"
)

FACILITY_LINE3 = Facility(
    facility_id="FAC-P04-L3",
    plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
    line_id="Line 3",
    cell_id="Cell 3-A (Final Drive Testing & Pack Out)"
)

FACILITY_WAREHOUSE = Facility(
    facility_id="FAC-P04-WH",
    plant_name="Nova Motors - Plant 04 (Bangalore, Karnataka)",
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

# ADDITIONAL SCALED PRODUCT SKUS
# Product 2: 400V Compact Drive Unit
SPEC_MH4410 = Specification(spec_id="SP-4410", part_number="MH-4410", dimension="Bore Diameter", nominal=38.0, tolerance_plus=0.015, tolerance_minus=0.015, unit="mm", material="Aluminum 6061", cad_reference="MH-4410_rev1.step")
SPEC_RS2201 = Specification(spec_id="SP-2201", part_number="RS-2201", dimension="Shaft Runout", nominal=0.0, tolerance_plus=0.004, tolerance_minus=0.004, unit="mm", material="Steel 4140", cad_reference="RS-2201_rev2.step")
SPEC_CB1044 = Specification(spec_id="SP-1044", part_number="CB-1044", dimension="Outer Diameter", nominal=20.0, tolerance_plus=0.008, tolerance_minus=0.008, unit="mm", material="Chrome Steel GCR15", cad_reference="CB-1044_rev1.step")
SPEC_SC2210 = Specification(spec_id="SP-2210", part_number="SC-2210", dimension="Lamination Stack", nominal=90.0, tolerance_plus=0.10, tolerance_minus=0.10, unit="mm", material="Electrical Steel", cad_reference="SC-2210_rev1.step")
SPEC_CP5500 = Specification(spec_id="SP-5500", part_number="CP-5500", dimension="Cooling Flatness", nominal=0.0, tolerance_plus=0.08, tolerance_minus=0.08, unit="mm", material="Brazed Aluminum", cad_reference="CP-5500_rev1.step")

PART_MH4410 = Part(part_number="MH-4410", name="Motor Housing 400V", tolerance_spec_id="SP-4410", approved_supplier_ids=["SUP-301"], substitute_part_numbers=[], in_stock_quantity=85, unit_cost_usd=280.00)
PART_RS2201 = Part(part_number="RS-2201", name="Rotor Shaft 400V", tolerance_spec_id="SP-2201", approved_supplier_ids=["SUP-304"], substitute_part_numbers=[], in_stock_quantity=110, unit_cost_usd=195.00)
PART_CB1044 = Part(part_number="CB-1044", name="Steel Bearing 400V", tolerance_spec_id="SP-1044", approved_supplier_ids=["SUP-302"], substitute_part_numbers=[], in_stock_quantity=320, unit_cost_usd=45.00)
PART_SC2210 = Part(part_number="SC-2210", name="Stator Core 400V", tolerance_spec_id="SP-2210", approved_supplier_ids=["SUP-303"], substitute_part_numbers=[], in_stock_quantity=95, unit_cost_usd=390.00)
PART_CP5500 = Part(part_number="CP-5500", name="Cooling Plate 400V", tolerance_spec_id="SP-5500", approved_supplier_ids=["SUP-301"], substitute_part_numbers=[], in_stock_quantity=180, unit_cost_usd=130.00)

PRODUCT_EV_DRV_400V = Product(
    sku="EV-DRV-400V",
    revision="Rev 2",
    name="400V Compact Electric Drive Unit",
    part_numbers=["MH-4410", "RS-2201", "CB-1044", "SC-2210", "CP-5500"],
    facility_id="FAC-P04-L3",
    specification_ids=["SP-4410", "SP-2201", "SP-1044", "SP-2210", "SP-5500"]
)

# Product 3: 100kWh High-Density Battery Pack
SPEC_BC9900 = Specification(spec_id="SP-9900", part_number="BC-9900", dimension="Enclosure Width", nominal=1200.0, tolerance_plus=0.50, tolerance_minus=0.50, unit="mm", material="Extruded Aluminum", cad_reference="BC-9900_rev3.step")
SPEC_BM1100 = Specification(spec_id="SP-1100", part_number="BM-1100", dimension="BMS Voltage Precision", nominal=0.0, tolerance_plus=0.002, tolerance_minus=0.002, unit="V", material="FR4 PCB assembly", cad_reference="BM-1100_rev1.step")
SPEC_CC4420 = Specification(spec_id="SP-4420", part_number="CC-4420", dimension="Copper Thickness", nominal=3.0, tolerance_plus=0.05, tolerance_minus=0.05, unit="mm", material="Pure Copper C101", cad_reference="CC-4420_rev1.step")
SPEC_CS3344 = Specification(spec_id="SP-3344", part_number="CS-3344", dimension="Sleeve Thickness", nominal=5.0, tolerance_plus=0.10, tolerance_minus=0.10, unit="mm", material="Thermal Silicone", cad_reference="CS-3344_rev1.step")

PART_BC9900 = Part(part_number="BC-9900", name="Battery Enclosure", tolerance_spec_id="SP-9900", approved_supplier_ids=["SUP-301"], substitute_part_numbers=[], in_stock_quantity=45, unit_cost_usd=950.00)
PART_BM1100 = Part(part_number="BM-1100", name="BMS Core Module", tolerance_spec_id="SP-1100", approved_supplier_ids=["SUP-302"], substitute_part_numbers=[], in_stock_quantity=90, unit_cost_usd=420.00)
PART_CC4420 = Part(part_number="CC-4420", name="Copper Busbars", tolerance_spec_id="SP-4420", approved_supplier_ids=["SUP-303"], substitute_part_numbers=[], in_stock_quantity=500, unit_cost_usd=85.00)
PART_CS3344 = Part(part_number="CS-3344", name="Thermal Cooling Sleeve", tolerance_spec_id="SP-3344", approved_supplier_ids=["SUP-304"], substitute_part_numbers=[], in_stock_quantity=150, unit_cost_usd=110.00)

PRODUCT_EV_BAT_100KWH = Product(
    sku="EV-BAT-100KWH",
    revision="Rev 3",
    name="100kWh High-Density Battery Pack",
    part_numbers=["BC-9900", "BM-1100", "CC-4420", "CS-3344"],
    facility_id="FAC-P04-L1",
    specification_ids=["SP-9900", "SP-1100", "SP-4420", "SP-3344"]
)

# Product 4: 800V SiC Inverter
SPEC_IGBT800 = Specification(spec_id="SP-800", part_number="IGBT-800", dimension="Module Junction Gap", nominal=0.50, tolerance_plus=0.01, tolerance_minus=0.01, unit="mm", material="Silicon Carbide (SiC)", cad_reference="IGBT-800_rev1.step")
SPEC_CAP100 = Specification(spec_id="SP-100", part_number="CAP-100", dimension="Capacitance Value", nominal=600.0, tolerance_plus=30.0, tolerance_minus=30.0, unit="uF", material="Polypropylene Film", cad_reference="CAP-100_rev1.step")
SPEC_PCBMAIN = Specification(spec_id="SP-PCB", part_number="PCB-MAIN", dimension="Board Warp", nominal=0.0, tolerance_plus=0.05, tolerance_minus=0.05, unit="mm", material="High TG FR4", cad_reference="PCB-MAIN_rev2.step")

PART_IGBT800 = Part(part_number="IGBT-800", name="SiC Power Module 800V", tolerance_spec_id="SP-800", approved_supplier_ids=["SUP-305"], substitute_part_numbers=[], in_stock_quantity=200, unit_cost_usd=620.00)
PART_CAP100 = Part(part_number="CAP-100", name="DC Link Capacitor 800V", tolerance_spec_id="SP-100", approved_supplier_ids=["SUP-302"], substitute_part_numbers=[], in_stock_quantity=310, unit_cost_usd=145.00)
PART_PCBMAIN = Part(part_number="PCB-MAIN", name="Inverter Logic Board", tolerance_spec_id="SP-PCB", approved_supplier_ids=["SUP-303"], substitute_part_numbers=[], in_stock_quantity=150, unit_cost_usd=180.00)

PRODUCT_EV_INV_800V = Product(
    sku="EV-INV-800V",
    revision="Rev 1",
    name="800V Silicon Carbide Inverter",
    part_numbers=["IGBT-800", "CAP-100", "PCB-MAIN"],
    facility_id="FAC-P04-L2",
    specification_ids=["SP-800", "SP-100", "SP-PCB"]
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

INITIAL_SPECIFICATIONS = [
    SPEC_MH8820, SPEC_MH8820_PC, SPEC_RS4401, SPEC_CB1099, SPEC_SC3310, SPEC_CP7700,
    SPEC_MH4410, SPEC_RS2201, SPEC_CB1044, SPEC_SC2210, SPEC_CP5500,
    SPEC_BC9900, SPEC_BM1100, SPEC_CC4420, SPEC_CS3344,
    SPEC_IGBT800, SPEC_CAP100, SPEC_PCBMAIN
]
INITIAL_SUPPLIERS = [
    SUPPLIER_TITAN_METALS, SUPPLIER_PRECISIONCAST, SUPPLIER_RAPID_COMPONENTS,
    SUPPLIER_FORGEWORKS, SUPPLIER_SKF_INDUSTRIAL
]
INITIAL_PARTS = [
    PART_MH8820, PART_MH8820_PC, PART_RS4401, PART_CB1099, PART_SC3310, PART_CP7700,
    PART_MH4410, PART_RS2201, PART_CB1044, PART_SC2210, PART_CP5500,
    PART_BC9900, PART_BM1100, PART_CC4420, PART_CS3344,
    PART_IGBT800, PART_CAP100, PART_PCBMAIN
]
INITIAL_FACILITIES = [FACILITY_LINE1, FACILITY_LINE2, FACILITY_LINE3, FACILITY_WAREHOUSE]
INITIAL_PRODUCTS = [
    PRODUCT_EV_POW_800V, PRODUCT_EV_DRV_400V, PRODUCT_EV_BAT_100KWH, PRODUCT_EV_INV_800V
]
INITIAL_SUBSTITUTIONS = [SUBSTITUTION_SUB001]

