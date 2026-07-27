"""
Unit & Lineage Resolution tests for Enterprise Asset Model (EAM) ground truth.
"""

import sys
from pathlib import Path
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from knowledge import EnterpriseAssetModel, KnowledgeGraph, AssetLineage


def test_enterprise_asset_model_structure():
    eam = EnterpriseAssetModel()

    assert "PLANT-04-BANGALORE" in eam.plants
    plant = eam.plants["PLANT-04-BANGALORE"]
    assert plant.name == "Nova Motors Bangalore Operations"
    assert len(plant.factories) > 0

    factory = plant.factories[0]
    assert factory.factory_id == "FAC-P04"
    assert len(factory.lines) == 4

    line_ids = [l.line_id for l in factory.lines]
    assert "Line 1" in line_ids
    assert "Line 2" in line_ids
    assert "Line 3" in line_ids
    assert "Warehouse" in line_ids

    line2 = next(l for l in factory.lines if l.line_id == "Line 2")
    assert len(line2.machines) == 4

    machine = next(m for m in line2.machines if m.machine_id == "CNC-102")
    assert len(machine.plcs) > 0

    plc = machine.plcs[0]
    assert plc.plc_id == "PLC-CNC-102"
    assert len(plc.sensors) > 0

    sensor_ids = [s.sensor_id for s in plc.sensors]
    assert "SENS-VIB-02" in sensor_ids

    assert "EV-POW-800V" in eam.products
    prod = eam.products["EV-POW-800V"]
    assert prod.sku == "EV-POW-800V"
    assert prod.line_id == "Line 2"
    assert prod.components[0].part_number == "MH-8820"


def test_asset_lineage_resolution():
    eam = EnterpriseAssetModel()

    # Resolve sensor lineage
    lineage = eam.resolve_lineage("SENS-VIB-02")
    assert lineage is not None
    assert lineage.plant_id == "PLANT-04-BANGALORE"
    assert lineage.factory_id == "FAC-P04"
    assert lineage.line_id == "Line 2"
    assert lineage.machine_id == "CNC-102"
    assert lineage.sensor_id == "SENS-VIB-02"
    assert "Nova Motors Bangalore Operations > Plant 04 Powertrain Assembly Factory > Line 2 Housing Machining & Inspection > Precision Finish Spindle > CNC-102 Controller PLC (Siemens S7-1500) > Spindle Vibration Sensor" == lineage.lineage_path


def test_knowledge_graph_asset_model_delegation():
    kg = KnowledgeGraph()
    lineage = kg.resolveAssetLineage("SENS-VIB-02")

    assert lineage is not None
    assert lineage.machine_id == "CNC-102"
