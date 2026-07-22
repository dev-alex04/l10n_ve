# Copyright (c) 2026, l10n_ve and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VEStampTaxRate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		rate: DF.Float
		state: DF.Link
		threshold: DF.Float
		threshold_unit: DF.Literal["U.T.", "VEF", "Sin umbral"]
	# end: auto-generated types

	pass
