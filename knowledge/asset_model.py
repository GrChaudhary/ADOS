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
        """Seeds ground truth operational asset model for ADOS manufacturing plants."""
        # Line 1 (Assembly & Cooling)
        plc_robot1 = PLC(plcId="PLC-ROBOT-01", name="Robot Arm Controller PLC", ipAddress="192.168.10.11", machineId="ROBOT-ARM-01", sensors=[])
        m_robot1 = Machine(machineId="ROBOT-ARM-01", name="Robot Arm Assembly Station", machineType="ROBOTIC_ARM", line_id="Line 1", plcs=[plc_robot1])
        
        plc_assy1 = PLC(plcId="PLC-ASSY-01", name="Assembly Conveyor Controller PLC", ipAddress="192.168.10.12", machineId="ASSY-LINE-01", sensors=[])
        m_assy1 = Machine(machineId="ASSY-LINE-01", name="Assembly Line Conveyor", machineType="CONVEYOR", line_id="Line 1", plcs=[plc_assy1])

        line1 = Line(lineId="Line 1", name="Line 1 Assembly & Cooling", factory_id="FAC-P1", machines=[m_robot1, m_assy1])

        # Line 2 (Machining & Fitting - Hero Incident Line)
        sns_vib_101 = Sensor(sensorId="SNS-VIB-101", name="CNC 101 Vibration Sensor", sensorType="vibration", unit="mm/s", plcId="PLC-CNC-101", currentValue=1.2)
        plc_cnc_101 = PLC(plcId="PLC-CNC-101", name="CNC 101 Controller PLC", ipAddress="192.168.10.21", machineId="CNC-101", sensors=[sns_vib_101])
        m_cnc_101 = Machine(machineId="CNC-101", name="Precision CNC Machining Center 101", machineType="CNC_MILL", line_id="Line 2", plcs=[plc_cnc_101])

        plc_insp_01 = PLC(plcId="PLC-INSP-01", name="Inspection Cell Controller PLC", ipAddress="192.168.10.22", machineId="INSP-CELL-01", sensors=[])
        m_insp_01 = Machine(machineId="INSP-CELL-01", name="Automated Optical Inspection Station 1", machineType="INSPECTION", line_id="Line 2", plcs=[plc_insp_01])

        line2 = Line(lineId="Line 2", name="Line 2 Machining & Fitting", factory_id="FAC-P1", machines=[m_cnc_101, m_insp_01])

        # Line 3 (High-Precision Housing Assembly)
        sns_vib = Sensor(sensorId="SNS-VIB-45", name="Spindle Bearing Vibration Sensor", sensorType="vibration", unit="mm/s", plcId="PLC-CNC-03", currentValue=4.8)
        sns_disp = Sensor(sensorId="SNS-DISP-01", name="Z-Axis Tool Offset Displacement Sensor", sensorType="displacement", unit="mm", plcId="PLC-CNC-03", currentValue=0.035)
        plc_cnc = PLC(plcId="PLC-CNC-03", name="Line 3 CNC Spindle Controller PLC", ipAddress="192.168.10.3", machineId="CNC-SPINDLE-03", sensors=[sns_vib, sns_disp])
        cnc_machine = Machine(machineId="CNC-SPINDLE-03", name="Precision CNC Spindle Station 3", machineType="CNC_MILL", line_id="Line 3", plcs=[plc_cnc])

        line3 = Line(lineId="Line 3", name="Line 3 High-Precision Housing Assembly", factory_id="FAC-P1", machines=[cnc_machine])

        # Warehouse (Inventory Staging)
        plc_wh = PLC(plcId="PLC-WH-01", name="Warehouse Staging Controller PLC", ipAddress="192.168.10.99", machineId="STAGING-BAY-01", sensors=[])
        m_wh = Machine(machineId="STAGING-BAY-01", name="Warehouse Staging Bay 1", machineType="STAGING", line_id="Warehouse", plcs=[plc_wh])

        warehouse = Line(lineId="Warehouse", name="Warehouse Inventory Staging", factory_id="FAC-P1", machines=[m_wh])

        # Factories
        factory1 = Factory(factoryId="FAC-P1", name="Plant 1 Main Assembly Facility", plant_id="PLANT-NA-01", lines=[line1, line2, line3, warehouse])

        # Plants
        plant_na = Plant(plantId="PLANT-NA-01", name="North America Operations Division", region="North America", factories=[factory1])

        self.plants[plant_na.plant_id] = plant_na

        # Components & Products
        comp_housing = Component(partNumber="MH-100", name="Motor Housing Part", specId="SP-100", approvedSupplierIds=["SUP-201", "SUP-202"])
        prod_housing = AssetProduct(sku="PROD-100", name="Motor Housing", lineId="Line 2", components=[comp_housing])

        self.products[prod_housing.sku] = prod_housing

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
