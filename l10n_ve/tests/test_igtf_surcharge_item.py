"""Producto 'Recargo por IGTF (3%)' sembrado por el setup.

Lo delicado no es que el ítem se cree, sino QUE NO se le cuelgue una alícuota que no le
corresponde: es un producto exento que va en documentos fiscales.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.setup import create_igtf_surcharge_item

ITEM_CODE = (
    "Recargo por Impuesto a las Grandes Transacciones Financieras (3%) "
    "aplicado a la factura afectada"
)
GROUP_NAME = "Recargos Fiscales"


class TestIGTFSurchargeItem(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # `create_igtf_surcharge_item` hace `frappe.db.commit()`, y el arbol de Item
        # Group commitea por su cuenta al recalcular lft/rgt. Con eso el rollback de
        # FrappeTestCase no alcanza y el item quedaba PERMANENTEMENTE en el site donde
        # corriera la suite --verificado: sobrevivia al tearDown--. Se neutraliza el
        # commit para que la transaccion de la prueba se pueda deshacer entera.
        parche = patch.object(frappe.db, "commit")
        self.addCleanup(parche.stop)
        parche.start()

    def test_creates_the_item_and_its_group(self):
        create_igtf_surcharge_item()

        self.assertTrue(frappe.db.exists("Item Group", GROUP_NAME))
        self.assertTrue(frappe.db.exists("Item", ITEM_CODE))

        item = frappe.get_doc("Item", ITEM_CODE)
        self.assertEqual(item.item_group, GROUP_NAME)
        self.assertEqual(item.is_stock_item, 0)
        self.assertEqual(item.vat_exempt, 1)

    def test_marks_it_as_a_service_when_the_field_exists(self):
        """El indicador Bien/Servicio lo crea el #580; acá se tolera su ausencia."""
        create_igtf_surcharge_item()

        item = frappe.get_doc("Item", ITEM_CODE)
        if item.meta.has_field("goods_or_service"):
            self.assertEqual(item.goods_or_service, "2 - Servicio")

    def test_never_links_a_non_exempt_tax_template(self):
        """Lo que de verdad hay que proteger: es un producto EXENTO.

        Antes, sin plantilla 'Exento', se buscaba `title like "%E%"` con `limit=1` y se
        le colgaba una alicuota cualquiera.
        """
        create_igtf_surcharge_item()

        for fila in frappe.get_doc("Item", ITEM_CODE).taxes:
            self.assertIn("exent", fila.item_tax_template.lower())

    def test_does_not_invent_a_template_when_there_is_none(self):
        """Sin plantilla exenta no se asocia ninguna, en vez de elegir una arbitraria."""
        with patch.object(frappe, "get_all", return_value=[]):
            create_igtf_surcharge_item()

        self.assertEqual(frappe.get_doc("Item", ITEM_CODE).taxes, [])

    def test_is_idempotent(self):
        create_igtf_surcharge_item()
        create_igtf_surcharge_item()

        self.assertEqual(
            frappe.db.count("Item", {"item_code": ITEM_CODE}),
            1,
            "una segunda corrida no debe duplicar el item",
        )

    def test_it_fails_loudly_when_there_is_no_root_group(self):
        """Sin raiz del arbol se corta, en vez de colgarlo de una rama cualquiera."""
        frappe.db.delete("Item Group", {"item_group_name": GROUP_NAME})

        with patch.object(frappe.db, "get_value", return_value=None), patch(
            "frappe.db.exists", return_value=False
        ):
            with self.assertRaises(frappe.ValidationError) as ctx:
                create_igtf_surcharge_item()

        self.assertIn("grupo raiz", str(ctx.exception).lower())
