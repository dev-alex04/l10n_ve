# Copyright (c) 2026, l10n_ve and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VEPaymentGovernmentWithholding(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Link | None
		actual_amount: DF.Currency
		base_amount: DF.Currency
		jurisdiction: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		rate: DF.Float
		suggested_amount: DF.Currency
		voucher_attachment: DF.Attach | None
		voucher_number: DF.Data | None
		withholding_type: DF.Literal["Timbre Fiscal", "ISAE", "Responsabilidad Social"]
	# end: auto-generated types

	pass
