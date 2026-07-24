# Copyright (c) 2026, l10n_ve and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VEGovernmentWithholding(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		municipality: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		state: DF.Link | None
		withholding_type: DF.Literal["Timbre Fiscal", "ISAE", "Responsabilidad Social"]
	# end: auto-generated types

	pass
