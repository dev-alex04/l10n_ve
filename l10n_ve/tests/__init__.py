# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

# Importar todos los módulos de test para que bench run-tests
# los descubra con --module l10n_ve.tests
from l10n_ve.tests.test_base_retention_builder import *  # noqa: F401,F403
from l10n_ve.tests.test_islr_payload_builder import *  # noqa: F401,F403
from l10n_ve.tests.test_islr_withholding_voucher import *  # noqa: F401,F403
from l10n_ve.tests.test_vat_withholding_voucher import *  # noqa: F401,F403
from l10n_ve.tests.test_islr_withholding_integration import *  # noqa: F401,F403
from l10n_ve.tests.test_islr_calculation import *  # noqa: F401,F403
from l10n_ve.tests.test_taxes_and_totals import *  # noqa: F401,F403
from l10n_ve.tests.test_taxes_mixin import *  # noqa: F401,F403
