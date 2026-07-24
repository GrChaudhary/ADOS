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

    assert "PLANT-NA-01" in eam.plants
    plant = eam.plants["PLANT-NA-01"]
    assert plant.name == "North America Operations Division"
    assert len(plant.factories) > 0

    factory = plant.factories[0]
    assert factory.factory_id == "FAC-P1"
    assert len(factory.lines) > 0

    line = factory.lines[0]
    assert line.line_id == "Line 3"
    assert len(line.machines) > 0

    machine = line.machines[0]
    assert machine.machine_id == "CNC-SPINDLE-03"
    assert len(machine.plcs) > 0

    plc = machine.plcs[0]
    assert plc.plc_id == "PLC-CNC-03"
    assert len(plc.sensors) > 0

    sensor = plc.sensors[0]
    assert sensor.sensor_id == "SNS-VIB-45"


def test_asset_lineage_resolution():
    eam = EnterpriseAssetModel()

    # Resolve sensor lineage
    lineage = eam.resolve_lineage("SNS-VIB-45")
    assert lineage is not None
    assert lineage.plant_id == "PLANT-NA-01"
    assert lineage.factory_id == "FAC-P1"
    assert lineage.line_id == "Line 3"
    assert lineage.machine_id == "CNC-SPINDLE-03"
    assert lineage.sensor_id == "SNS-VIB-45"
    assert "North America Operations Division > Plant 1 Main Assembly Facility > Line 3 High-Precision Housing Assembly > Precision CNC Spindle Station 3 > Line 3 CNC Spindle Controller PLC > Spindle Bearing Vibration Sensor" == lineage.lineage_path


def test_knowledge_graph_asset_model_delegation():
    kg = KnowledgeGraph()
    lineage = kg.resolveAssetLineage("SNS-VIB-45")

    assert lineage is not None
    assert lineage.machine_id == "CNC-SPINDLE-03"
