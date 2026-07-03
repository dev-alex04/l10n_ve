"""Asigna el logotipo predeterminado a los bancos venezolanos existentes.

Para cada banco en la lista oficial de Venezuela, si aún no tiene imagen
configurada, se le asigna la ruta al logo almacenado en los assets de l10n_ve.
Los logos personalizados subidos manualmente desde el Desk no son sobrescritos.
"""
import json
import os
from typing import Optional

import frappe


def execute() -> None:
    if not frappe.db.has_column("Bank", "image"):
        print("  ⚠ El campo 'image' no existe en Bank. Ejecutar bench migrate primero.")
        return

    app_path: str = frappe.get_app_path("l10n_ve")
    json_path: str = os.path.join(app_path, "resources", "Bank_venezuelan.json")

    if not os.path.exists(json_path):
        print(f"  ⚠ No se encontró el archivo de bancos venezolanos: {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        bancos: list[dict] = json.load(f)

    actualizados: int = 0
    omitidos: int = 0

    for banco_data in bancos:
        codigo_banco: Optional[str] = banco_data.get("codigo")
        nombre_banco: Optional[str] = banco_data.get("nombre")
        imagen_banco: Optional[str] = banco_data.get("image")

        if not codigo_banco or not nombre_banco or not imagen_banco:
            continue

        # Buscar el banco por código SWIFT o por nombre
        bank_name: Optional[str] = (
            frappe.db.get_value("Bank", {"swift_number": codigo_banco}, "name")
            or frappe.db.get_value("Bank", {"bank_name": nombre_banco}, "name")
        )

        if not bank_name:
            print(f"  -- Banco no encontrado en DB: '{nombre_banco}' ({codigo_banco}), se omite.")
            omitidos += 1
            continue

        imagen_actual: Optional[str] = frappe.get_cached_value("Bank", bank_name, "image")

        if imagen_actual:
            # Respetar el logo personalizado cargado manualmente por el usuario
            omitidos += 1
            continue

        frappe.db.set_value("Bank", bank_name, "image", imagen_banco, update_modified=False)
        actualizados += 1
        print(f"  -> Logo asignado: '{nombre_banco}' ({codigo_banco})")

    frappe.cache().delete_value("l10n_ve:portal_banks_v2")
    print(f"\n  ✔ Logos de bancos actualizados: {actualizados}, omitidos: {omitidos}")
