import frappe
from frappe import _

from erpnext.stock.doctype.item.item import Item

from l10n_ve.utils.utils import get_reference_currency


class CustomItem(Item):


    def validate(self):
        super().validate()
        company = self.get("company")
        if not company:
            company = frappe.db.get_single_value("Global Defaults", "default_company")

        if not self.reference_currency and company:
            self.reference_currency = frappe.db.get_value("Company", company, "reference_currency")

        if not self.reference_currency:
            self.reference_currency = "USD"

    def after_insert(self) -> None:
        super().after_insert()

        self.create_purchase_price()

    def add_price(self, price_list=None) -> None:
        """Add a new sales price"""

        if not self.is_valid_for_create_price:
            return

        if not price_list:
            price_list = frappe.db.get_single_value(
                "Selling Settings", "selling_price_list"
            ) or frappe.db.get_value("Price List", _("Standard Selling"))

        if price_list:
            item_price = frappe.get_doc(
                {
                    "doctype": "Item Price",
                    "price_list": price_list,
                    "item_code": self.name,
                    "uom": self.stock_uom,
                    "brand": self.brand,
                    "currency": get_reference_currency(),
                    "price_list_rate": self.standard_rate,
                })

            item_price.insert()

            self.sales_actual_price = item_price.name


    def create_purchase_price(self) -> None:
        """Add a new purchase price"""

        if not self.is_valid_for_create_price:
            return

        price_list = frappe.db.get_value("Price List", _("Standard Buying"))

        if price_list:
            item_price = frappe.get_doc(
                {
                    "doctype": "Item Price",
                    "price_list": price_list,
                    "item_code": self.name,
                    "uom": self.stock_uom,
                    "brand": self.brand,
                    "currency": get_reference_currency(),
                    "price_list_rate": self.standard_purchase_rate,
                })

            item_price.insert()

            self.purchase_actual_price = item_price.name

    @property
    def is_valid_for_create_price(self) -> bool:

        is_valid_for_create_price = not any([
            bool(self.has_variants),
            bool(not self.standard_rate and not self.standard_purchase_rate)
        ])

        return is_valid_for_create_price
