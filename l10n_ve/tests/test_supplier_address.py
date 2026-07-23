# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

class TestSupplierAddress(FrappeTestCase):
    def setUp(self) -> None:
        # Clean up any test suppliers/addresses to avoid conflicts
        frappe.db.delete("Dynamic Link", {"link_doctype": "Supplier", "link_name": ["in", ["_Test Supplier Address 1", "_Test Supplier Address 2"]]})
        frappe.db.delete("Supplier", {"name": ["in", ["_Test Supplier Address 1", "_Test Supplier Address 2"]]})
        frappe.db.delete("Address", {"address_title": ["in", ["_Test Address 1", "_Test Address 2"]]})
        frappe.db.commit()

    def tearDown(self) -> None:
        # Clean up
        frappe.db.delete("Dynamic Link", {"link_doctype": "Supplier", "link_name": ["in", ["_Test Supplier Address 1", "_Test Supplier Address 2"]]})
        frappe.db.delete("Supplier", {"name": ["in", ["_Test Supplier Address 1", "_Test Supplier Address 2"]]})
        frappe.db.delete("Address", {"address_title": ["in", ["_Test Address 1", "_Test Address 2"]]})
        frappe.db.commit()

    def test_supplier_address_uniqueness(self) -> None:
        # Get valid database values for mandatory fields in l10n_ve address
        state = frappe.db.get_value("VE State", {}, "name")
        city = frappe.db.get_value("VE City", {}, "name")
        county = frappe.db.get_value("VE Municipality", {}, "name")
        supplier_group = frappe.db.get_value("Supplier Group", {}, "name")

        # 1. Create a primary address
        addr1 = frappe.new_doc("Address")
        addr1.address_title = "_Test Address 1"
        addr1.address_type = "Billing"
        addr1.address_line1 = "_Test Line 1"
        addr1.country = "Venezuela, Bolivarian Republic of"
        addr1.state = state
        addr1.city = city
        addr1.county = county
        addr1.insert(ignore_permissions=True)
        
        # 2. Create a supplier and link to addr1
        sup1 = frappe.new_doc("Supplier")
        sup1.supplier_name = "_Test Supplier Address 1"
        sup1.supplier_group = supplier_group
        sup1.supplier_type = "Company"
        sup1.type_of_document = "RIF"
        sup1.nature_of_the_taxpayer = "Venezuelan"
        sup1.type_of_person = "Natural person domiciled"
        sup1.tax_id = "V111111111"
        sup1.supplier_primary_address = addr1.name
        sup1.insert(ignore_permissions=True)
        
        # 3. Create another address
        addr2 = frappe.new_doc("Address")
        addr2.address_title = "_Test Address 2"
        addr2.address_type = "Billing"
        addr2.address_line1 = "_Test Line 2"
        addr2.country = "Venezuela, Bolivarian Republic of"
        addr2.state = state
        addr2.city = city
        addr2.county = county
        addr2.insert(ignore_permissions=True)
        
        # 4. Create another supplier and try to link to the same addr1 (should fail)
        sup2 = frappe.new_doc("Supplier")
        sup2.supplier_name = "_Test Supplier Address 2"
        sup2.supplier_group = supplier_group
        sup2.supplier_type = "Company"
        sup2.type_of_document = "RIF"
        sup2.nature_of_the_taxpayer = "Venezuelan"
        sup2.type_of_person = "Natural person domiciled"
        sup2.tax_id = "V222222222"
        sup2.supplier_primary_address = addr1.name
        
        # Expect ValidationError
        with self.assertRaises(frappe.ValidationError):
            sup2.insert(ignore_permissions=True)
            
        # 5. Link to addr2 instead (should succeed)
        sup2.supplier_primary_address = addr2.name
        sup2.insert(ignore_permissions=True)
