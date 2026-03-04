import frappe

from erpnext.stock.doctype.item_price.item_price import ItemPrice


class CustomItemPrice(ItemPrice):

    def after_insert(self) -> None:
        self.set_price_on_item()

    def on_update(self) -> None:
        self.set_price_on_item()

    def set_price_on_item(self) -> None:
        price_type = 'sales' if self.selling else 'purchase'

        frappe.db.set_value('Item',
                            self.item_code,
                            f'{price_type}_actual_price',
                            self.name)

        # Añade esta sección para guardar el monto en los campos de datos para su visualización
        frappe.db.set_value('Item',
                            self.item_code,
                            f'price_{price_type}',
                            self.price_list_rate)
