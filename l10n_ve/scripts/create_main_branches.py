"""Crea la sucursal principal de las compañías que todavía no tienen ninguna.

Las compañías nuevas la reciben al crearse (`CustomCompany.on_update`); esto cubre las que ya
existían. Manual y con ensayo por defecto; `bench execute` hace el commit al terminar:

    bench --site <sitio> execute l10n_ve.scripts.create_main_branches.execute
    bench --site <sitio> execute l10n_ve.scripts.create_main_branches.execute --kwargs "{'dry_run': False}"
"""

import frappe

from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import ensure_main_branch


def execute(dry_run: bool = True) -> None:
    for company in frappe.get_all("Company", pluck="name", order_by="name"):
        _created, detail = ensure_main_branch(company, dry_run=dry_run)
        print(f"{company}: {detail}")
