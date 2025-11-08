# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
import csv
import os

import frappe
from frappe.utils.nestedset import NestedSet

class VEEconomicActivity(NestedSet):
	pass

@frappe.whitelist()
def get_economic_activity_options(sector=None, group=None):
	"""
	Devuelve una lista de opciones para los campos 'group' o 'branch'
	leyendo directamente desde el archivo CSV.
	"""
	csv_file_path = frappe.get_app_path('l10n_ve', 
									    'resources', 
									    've_economic_activity.csv')
	
	if not os.path.exists(csv_file_path):
		frappe.log_error("El archivo ve_economic_activity.csv no fue encontrado.", 
				          "Error en get_economic_activity_options")
		return []

	try:
		
		with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
			reader = csv.DictReader(file)
			activities = list(reader)
			
	except Exception as e:
		frappe.log_error(f"Error al leer el archivo CSV: {e}", 
				         "Error en get_economic_activity_options")
		return []

	if not sector:
		return []

	if sector and not group:
		groups = set()
		for row in activities:
			if row.get("sector") == sector and row.get("group"):
				groups.add(row["group"])
		return sorted(list(groups))


	if sector and group:
		branches = set()
		groups_in_sector = set()
		for row in activities:

			if row.get("sector") == sector and row.get("group") == group and row.get("branch"):
				branches.add(row["branch"])

			if row.get("sector") == sector and row.get("group"):
				groups_in_sector.add(row["group"])

		combined_options = branches.union(groups_in_sector)
		return sorted(list(combined_options))

	return []
