"""
Enterprise Knowledge Graph store implementation per docs/002-knowledge-graph.md.
"""

from typing import Dict, List, Optional, Union
from .models import Product, Part, Supplier, Facility, Specification, Substitution
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

    def resolveAssetLineage(self, asset_id: str) -> Optional[AssetLineage]:
        """
        Delegates physical asset topology lineage resolution to the operational EnterpriseAssetModel.
        """
        return self.asset_model.resolve_lineage(asset_id)
