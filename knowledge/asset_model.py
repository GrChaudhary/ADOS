"""
Enterprise Asset Model (EAM) implementation (knowledge/asset_model.py).
Provides operational ground truth for physical plant topology:
Plant -> Factory -> Line -> Machine -> PLC -> Sensor -> Product -> Component.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class Sensor(BaseModel):
    """Ground truth Sensor entity."""
    model_config = ConfigDict(populate_by_name=True)

    sensor_id: str = Field(..., alias="sensorId")
    name: str
    sensor_type: str = Field(..., alias="sensorType", description="vibration | displacement | humidity | vision")
    unit: str = Field(default="mm/s")
    plc_id: str = Field(..., alias="plcId")
    current_value: Optional[float] = Field(default=None, alias="currentValue")


class PLC(BaseModel):
    """Ground truth PLC (Programmable Logic Controller) entity."""
    model_config = ConfigDict(populate_by_name=True)

    plc_id: str = Field(..., alias="plcId")
    name: str
    ip_address: str = Field(default="192.168.1.10", alias="ipAddress")
    machine_id: str = Field(..., alias="machineId")
    sensors: List[Sensor] = Field(default_factory=list)


class Machine(BaseModel):
    """Ground truth Manufacturing Machine entity."""
    model_config = ConfigDict(populate_by_name=True)

    machine_id: str = Field(..., alias="machineId")
    name: str
    machine_type: str = Field(default="CNC_MILL", alias="machineType")
    line_id: str = Field(..., alias="lineId")
    plcs: List[PLC] = Field(default_factory=list)


class Line(BaseModel):
    """Ground truth Assembly/Production Line entity."""
    model_config = ConfigDict(populate_by_name=True)

    line_id: str = Field(..., alias="lineId")
    name: str
    factory_id: str = Field(..., alias="factoryId")
    machines: List[Machine] = Field(default_factory=list)


class Factory(BaseModel):
    """Ground truth Factory facility entity."""
    model_config = ConfigDict(populate_by_name=True)

    factory_id: str = Field(..., alias="factoryId")
    name: str
    plant_id: str = Field(..., alias="plantId")
    lines: List[Line] = Field(default_factory=list)


class Plant(BaseModel):
    """Ground truth Enterprise Plant entity."""
    model_config = ConfigDict(populate_by_name=True)

    plant_id: str = Field(..., alias="plantId")
    name: str
    region: str = Field(default="North America")
    factories: List[Factory] = Field(default_factory=list)


class Component(BaseModel):
    """Ground truth Component / Part entity."""
    model_config = ConfigDict(populate_by_name=True)

    part_number: str = Field(..., alias="partNumber")
    name: str
    spec_id: Optional[str] = Field(default=None, alias="specId")
    approved_supplier_ids: List[str] = Field(default_factory=list, alias="approvedSupplierIds")


class AssetProduct(BaseModel):
    """Ground truth Product SKU entity."""
    model_config = ConfigDict(populate_by_name=True)

    sku: str
    name: str
    line_id: str = Field(..., alias="lineId")
    components: List[Component] = Field(default_factory=list)


class AssetLineage(BaseModel):
    """Full operational lineage path resolved from ground truth Enterprise Asset Model."""
    model_config = ConfigDict(populate_by_name=True)

    plant_id: str = Field(..., alias="plantId")
    plant_name: str = Field(..., alias="plantName")
    factory_id: str = Field(..., alias="factoryId")
    factory_name: str = Field(..., alias="factoryName")
    line_id: str = Field(..., alias="lineId")
    line_name: str = Field(..., alias="lineName")
    machine_id: Optional[str] = Field(default=None, alias="machineId")
    machine_name: Optional[str] = Field(default=None, alias="machineName")
    plc_id: Optional[str] = Field(default=None, alias="plcId")
    sensor_id: Optional[str] = Field(default=None, alias="sensorId")
    lineage_path: str = Field(..., alias="lineagePath")


class EnterpriseAssetModel:
    """
    Authoritative operational ground truth store for Enterprise Asset Model.
    Manages Plant -> Factory -> Line -> Machine -> PLC -> Sensor -> Product -> Component topology.
    """

    def __init__(self, seed: bool = True):
        self.plants: Dict[str, Plant] = {}
        self.products: Dict[str, AssetProduct] = {}

        if seed:
            self._seed_ground_truth()

    def _seed_ground_truth(self) -> None:
        """Seeds ground truth operational asset model for Nova Motors Plant 04
        (Austin, TX) per documentation/02_Demo_Dataset_and_Digital_Twin.md."""
        # Line 1 (Stator & Rotor Cell)
        plc_stator = PLC(plcId="PLC-STATOR-01", name="Stator Winding Controller PLC", ipAddress="192.168.10.11", machineId="STATOR-WIND-01", sensors=[])
        m_stator = Machine(machineId="STATOR-WIND-01", name="Stator Winding Station", machineType="WINDING", line_id="Line 1", plcs=[plc_stator])

        plc_rotor = PLC(plcId="PLC-ROTOR-01", name="Rotor Assembly Controller PLC", ipAddress="192.168.10.12", machineId="ROTOR-ASSY-01", sensors=[])
        m_rotor = Machine(machineId="ROTOR-ASSY-01", name="Rotor Assembly Cell", machineType="ASSEMBLY", line_id="Line 1", plcs=[plc_rotor])

        line1 = Line(lineId="Line 1", name="Line 1 Stator & Rotor Cell", factory_id="FAC-P04", machines=[m_stator, m_rotor])

        # Line 2 (Housing Machining & Inspection - Hero Incident Line)
        sns_vib_02 = Sensor(sensorId="SENS-VIB-02", name="Spindle Vibration Sensor", sensorType="vibration", unit="mm/s", plcId="PLC-CNC-102", currentValue=4.8)
        sns_temp_04 = Sensor(sensorId="SENS-TEMP-04", name="Bearing Temperature Sensor", sensorType="temperature", unit="C", plcId="PLC-CNC-102", currentValue=58.2)
        plc_cnc_101 = PLC(plcId="PLC-CNC-101", name="CNC-101 Controller PLC", ipAddress="192.168.10.21", machineId="CNC-101", sensors=[])
        m_cnc_101 = Machine(machineId="CNC-101", name="Pre-Roughing Spindle (Tooling Assembly T-882)", machineType="CNC_MILL", line_id="Line 2", plcs=[plc_cnc_101])

        plc_cnc_102 = PLC(plcId="PLC-CNC-102", name="CNC-102 Controller PLC (Siemens S7-1500)", ipAddress="192.168.10.42", machineId="CNC-102", sensors=[sns_vib_02, sns_temp_04])
        m_cnc_102 = Machine(machineId="CNC-102", name="Precision Finish Spindle", machineType="CNC_MILL", line_id="Line 2", plcs=[plc_cnc_102])

        plc_rob_401 = PLC(plcId="PLC-ROB-401", name="Robotic Transfer Arm Controller PLC", ipAddress="192.168.10.43", machineId="ROB-401", sensors=[])
        m_rob_401 = Machine(machineId="ROB-401", name="6-Axis Robotic Transfer Arm", machineType="ROBOTIC_ARM", line_id="Line 2", plcs=[plc_rob_401])

        sns_opt_01 = Sensor(sensorId="SENS-OPT-01", name="Laser Optical Micrometer", sensorType="displacement", unit="mm", plcId="PLC-CMM-02", currentValue=0.031)
        plc_cmm_02 = PLC(plcId="PLC-CMM-02", name="CMM-02 Controller PLC", ipAddress="192.168.10.44", machineId="CMM-02", sensors=[sns_opt_01])
        m_cmm_02 = Machine(machineId="CMM-02", name="Automated Laser Coordinate Measurement Machine", machineType="INSPECTION", line_id="Line 2", plcs=[plc_cmm_02])

        line2 = Line(lineId="Line 2", name="Line 2 Housing Machining & Inspection", factory_id="FAC-P04", machines=[m_cnc_101, m_cnc_102, m_rob_401, m_cmm_02])

        # Line 3 (Final Drive Testing & Pack Out)
        plc_test = PLC(plcId="PLC-TEST-01", name="Final Drive Test Bench Controller PLC", ipAddress="192.168.10.31", machineId="TEST-BENCH-01", sensors=[])
        m_test = Machine(machineId="TEST-BENCH-01", name="Final Drive Test Bench", machineType="TEST_STAND", line_id="Line 3", plcs=[plc_test])

        plc_pack = PLC(plcId="PLC-PACK-01", name="Pack-Out Station Controller PLC", ipAddress="192.168.10.32", machineId="PACKOUT-01", sensors=[])
        m_pack = Machine(machineId="PACKOUT-01", name="Pack-Out Station", machineType="PACKAGING", line_id="Line 3", plcs=[plc_pack])

        line3 = Line(lineId="Line 3", name="Line 3 Final Drive Testing & Pack Out", factory_id="FAC-P04", machines=[m_test, m_pack])

        # Warehouse (Central Warehouse Automated Storage & Retrieval)
        plc_wh = PLC(plcId="PLC-WH-01", name="Warehouse ASRS Controller PLC", ipAddress="192.168.10.99", machineId="ASRS-01", sensors=[])
        m_wh = Machine(machineId="ASRS-01", name="Central Warehouse ASRS Bay", machineType="STAGING", line_id="Warehouse", plcs=[plc_wh])

        warehouse = Line(lineId="Warehouse", name="Central Warehouse (Austin ASRS)", factory_id="FAC-P04", machines=[m_wh])

        # Factories
        factory1 = Factory(factoryId="FAC-P04", name="Plant 04 Powertrain Assembly Factory", plant_id="PLANT-04-AUSTIN", lines=[line1, line2, line3, warehouse])

        # Plants
        plant_austin = Plant(plantId="PLANT-04-AUSTIN", name="Nova Motors Austin Operations", region="North America", factories=[factory1])

        self.plants[plant_austin.plant_id] = plant_austin

        # Components & Products
        comp_housing = Component(partNumber="MH-8820", name="Motor Housing", specId="SP-8820", approvedSupplierIds=["SUP-301", "SUP-302"])
        prod_drive_unit = AssetProduct(sku="EV-POW-800V", name="800V High-Performance Electric Drive Unit", lineId="Line 2", components=[comp_housing])

        self.products[prod_drive_unit.sku] = prod_drive_unit

    def resolve_lineage(self, asset_id: str) -> Optional[AssetLineage]:
        """
        Resolves operational ground truth lineage for a sensor, machine, line, or plant ID.
        Returns: Plant -> Factory -> Line -> Machine -> PLC -> Sensor path string.
        """
        for p in self.plants.values():
            for f in p.factories:
                for l in f.lines:
                    if l.line_id == asset_id or l.name == asset_id:
                        return AssetLineage(
                            plantId=p.plant_id,
                            plantName=p.name,
                            factoryId=f.factory_id,
                            factoryName=f.name,
                            lineId=l.line_id,
                            lineName=l.name,
                            lineagePath=f"{p.name} > {f.name} > {l.name}"
                        )
                    for m in l.machines:
                        if m.machine_id == asset_id:
                            return AssetLineage(
                                plantId=p.plant_id,
                                plantName=p.name,
                                factoryId=f.factory_id,
                                factoryName=f.name,
                                lineId=l.line_id,
                                lineName=l.name,
                                machineId=m.machine_id,
                                machineName=m.name,
                                lineagePath=f"{p.name} > {f.name} > {l.name} > {m.name}"
                            )
                        for plc in m.plcs:
                            for s in plc.sensors:
                                if s.sensor_id == asset_id:
                                    return AssetLineage(
                                        plantId=p.plant_id,
                                        plantName=p.name,
                                        factoryId=f.factory_id,
                                        factoryName=f.name,
                                        lineId=l.line_id,
                                        lineName=l.name,
                                        machineId=m.machine_id,
                                        machineName=m.name,
                                        plcId=plc.plc_id,
                                        sensorId=s.sensor_id,
                                        lineagePath=f"{p.name} > {f.name} > {l.name} > {m.name} > {plc.name} > {s.name}"
                                    )

        return None
