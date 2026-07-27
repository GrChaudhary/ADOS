"""
Enterprise Knowledge Graph store implementation per docs/002-knowledge-graph.md.
"""

from typing import Dict, List, Optional, Union
from .models import Product, Part, Supplier, Facility, Specification, Substitution, GraphNode, GraphEdge, KnowledgeGraphSnapshot
from .asset_model import EnterpriseAssetModel, AssetLineage
from .seed_data import (
    INITIAL_PRODUCTS, INITIAL_PARTS, INITIAL_SUPPLIERS,
    INITIAL_FACILITIES, INITIAL_SPECIFICATIONS, INITIAL_SUBSTITUTIONS
)


class KnowledgeGraph:
    """
    Materialized Enterprise Knowledge Graph store for semantic reasoning.
    Delegates operational ground truth asset topology to EnterpriseAssetModel.
    """

    def __init__(self, seed: bool = True, asset_model: Optional[EnterpriseAssetModel] = None):
        self.asset_model: EnterpriseAssetModel = asset_model or EnterpriseAssetModel(seed=seed)
        self._products: Dict[str, Product] = {}
        self._parts: Dict[str, Part] = {}
        self._suppliers: Dict[str, Supplier] = {}
        self._facilities: Dict[str, Facility] = {}
        self._specifications: Dict[str, Specification] = {}  # key: spec_id or part_number
        self._spec_by_part: Dict[str, Specification] = {}
        self._substitutions: Dict[str, Substitution] = {}

        if seed:
            self._load_seed_data()

    def _load_seed_data(self) -> None:
        for spec in INITIAL_SPECIFICATIONS:
            self.add_specification(spec)
        for supplier in INITIAL_SUPPLIERS:
            self.add_supplier(supplier)
        for part in INITIAL_PARTS:
            self.add_part(part)
        for facility in INITIAL_FACILITIES:
            self.add_facility(facility)
        for product in INITIAL_PRODUCTS:
            self.add_product(product)
        for sub in INITIAL_SUBSTITUTIONS:
            self.add_substitution(sub)

    def add_specification(self, spec: Specification) -> None:
        self._specifications[spec.spec_id] = spec
        self._spec_by_part[spec.part_number] = spec

    def add_supplier(self, supplier: Supplier) -> None:
        self._suppliers[supplier.supplier_id] = supplier

    def add_part(self, part: Part) -> None:
        self._parts[part.part_number] = part

    def add_facility(self, facility: Facility) -> None:
        self._facilities[facility.facility_id] = facility

    def add_product(self, product: Product) -> None:
        self._products[product.sku] = product

    def add_substitution(self, sub: Substitution) -> None:
        self._substitutions[sub.substitution_id] = sub

    # --- Mandatory Query Surface per docs/002-knowledge-graph.md ---

    def findAffectedProducts(self, defect_spec: Union[Specification, str]) -> List[Product]:
        """
        Answers 'what products/lines are affected by defect/spec X'.
        """
        target_spec_id = defect_spec.spec_id if isinstance(defect_spec, Specification) else defect_spec
        target_part_number = defect_spec.part_number if isinstance(defect_spec, Specification) else None

        affected: List[Product] = []
        for product in self._products.values():
            if target_spec_id in product.specification_ids:
                affected.append(product)
            elif target_part_number and target_part_number in product.part_numbers:
                affected.append(product)

        return affected

    def findApprovedSubstitutes(self, part_number: str) -> List[Part]:
        """
        Answers 'what approved substitutes exist for part Y'.
        Returns list of Part objects corresponding to approved substitute parts.
        """
        part = self._parts.get(part_number)
        if not part:
            return []

        substitutes: List[Part] = []
        for sub_pn in part.substitute_part_numbers:
            sub_part = self._parts.get(sub_pn)
            if sub_part:
                substitutes.append(sub_part)

        # Also search active pre-approved substitutions table
        for sub_rule in self._substitutions.values():
            if sub_rule.source_part_number == part_number and sub_rule.approval_status == "PRE_APPROVED":
                target_part = self._parts.get(sub_rule.target_part_number)
                if target_part and target_part not in substitutes:
                    substitutes.append(target_part)

        return substitutes

    def getSpecification(self, part_number: str) -> Optional[Specification]:
        """
        Retrieves the governing Specification entity for a given part number.
        """
        return self._spec_by_part.get(part_number)

    # --- Auxiliary Query Methods ---

    def get_part(self, part_number: str) -> Optional[Part]:
        return self._parts.get(part_number)

    def get_product(self, sku: str) -> Optional[Product]:
        return self._products.get(sku)

    def get_supplier(self, supplier_id: str) -> Optional[Supplier]:
        return self._suppliers.get(supplier_id)

    def list_substitutions_for_part(self, part_number: str) -> List[Substitution]:
        return [s for s in self._substitutions.values() if s.source_part_number == part_number]

    def list_products(self) -> List[Product]:
        return list(self._products.values())

    def list_parts(self) -> List[Part]:
        return list(self._parts.values())

    def list_suppliers(self) -> List[Supplier]:
        return list(self._suppliers.values())

    def resolveAssetLineage(self, asset_id: str) -> Optional[AssetLineage]:
        """
        Delegates physical asset topology lineage resolution to the operational EnterpriseAssetModel.
        """
        return self.asset_model.resolve_lineage(asset_id)

    # --- Knowledge Explorer (/knowledge) graph projection ---

    def build_graph_snapshot(self) -> KnowledgeGraphSnapshot:
        """
        Projects the BOM/supplier relationships in this store into a
        nodes/edges shape for the Knowledge Explorer graph view.
        """
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []

        for product in self.list_products():
            nodes.append(GraphNode(
                id=product.sku,
                type="PRODUCT",
                label=product.name,
                detail={
                    "sku": product.sku,
                    "revision": product.revision,
                    "name": product.name,
                    "facilityId": product.facility_id,
                },
            ))
            for part_number in product.part_numbers:
                edges.append(GraphEdge(
                    id=f"bom-{product.sku}-{part_number}",
                    source=product.sku,
                    target=part_number,
                    type="BOM",
                ))

        for part in self.list_parts():
            nodes.append(GraphNode(
                id=part.part_number,
                type="PART",
                label=part.name,
                detail={
                    "partNumber": part.part_number,
                    "name": part.name,
                    "inStockQuantity": part.in_stock_quantity,
                    "unitCostUsd": part.unit_cost_usd,
                },
            ))
            for supplier_id in part.approved_supplier_ids:
                edges.append(GraphEdge(
                    id=f"supplies-{part.part_number}-{supplier_id}",
                    source=part.part_number,
                    target=supplier_id,
                    type="SUPPLIES",
                ))
            for sub_part_number in part.substitute_part_numbers:
                sub_rule = next(
                    (s for s in self.list_substitutions_for_part(part.part_number) if s.target_part_number == sub_part_number),
                    None,
                )
                label = f"+${sub_rule.cost_delta_usd:,.0f}" if sub_rule else None
                edges.append(GraphEdge(
                    id=f"substitute-{part.part_number}-{sub_part_number}",
                    source=part.part_number,
                    target=sub_part_number,
                    type="SUBSTITUTE",
                    label=label,
                ))

        for supplier in self.list_suppliers():
            nodes.append(GraphNode(
                id=supplier.supplier_id,
                type="SUPPLIER",
                label=supplier.name,
                detail={
                    "supplierId": supplier.supplier_id,
                    "name": supplier.name,
                    "region": supplier.region,
                    "qualificationStatus": supplier.qualification_status,
                    "leadTimeDays": supplier.lead_time_days,
                    "capacityUnitsPerWeek": supplier.capacity_units_per_week,
                },
            ))

        return KnowledgeGraphSnapshot(nodes=nodes, edges=edges)
