# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

# Acá NO se registran los módulos de test, a propósito. `run-tests --app l10n_ve`
# —lo que corre CI, .github/workflows/ci.yml— los descubre recorriendo el árbol y
# tomando todo `test_*.py` (`frappe/test_runner.py`, `run_all_tests`), así que un
# archivo nuevo entra a la suite por existir, sin que nadie lo anote en ningún lado.
#
# Hasta acá vivía un `import *` por módulo, para que `--module l10n_ve.tests` corriera
# "toda" la suite. Era una segunda lista, mantenida a mano, y se desactualizó sola: al
# retirarla cubría 10 de los 54 archivos bajo `tests/` —156 de los 762 tests que colecta
# la app, el 20%—, y por definición nunca podía alcanzar los 29 `test_*.py` que viven
# fuera de `tests/` (doctypes, digital_invoice). Quien corriera ese comando se saltaba
# el 80% de la suite y leía verde.
#
# El modo de fallar era doblemente mudo: además del archivo que nadie anota, un
# `import *` pisa dos clases del mismo nombre en módulos distintos sin decir nada, así
# que la lista podía encoger sin cambiar de largo (medido al retirarla: 156 sueltos =
# 156 agregados, o sea que no había colisiones, pero nada avisaría si aparecieran).
# Mismo cambio que en domina_isp (Grupo-Altia/domina_isp#792).
#
# Para correr:
#   toda la suite → bench --site <site> run-tests --app l10n_ve --skip-test-records
#   un módulo     → bench --site <site> run-tests --module l10n_ve.tests.<modulo>


def load_tests(loader, tests, pattern):
    """Revienta a propósito si alguien corre `--module l10n_ve.tests`.

    Sin esto el comando termina en 0 (`Ran 0 tests`) y quien tenga memorizada la
    ruta vieja —o el documento que la cite— lee verde donde no corrió nada, que es
    peor que el registro desactualizado que esto reemplaza. Ojo: `run-tests` sale
    con código != 0 sólo si la variable de entorno CI está puesta, así que fuera de
    CI el resumen de unittest es el único veredicto.

    No afecta a los submódulos: unittest consulta este hook solo al cargar el
    paquete en sí, no al cargar `l10n_ve.tests.<lo.que.sea>`.
    """
    raise RuntimeError(
        "l10n_ve.tests ya no registra módulos: la suite se descubre por archivo. "
        "Usá `run-tests --app l10n_ve` para toda la suite, o "
        "`run-tests --module l10n_ve.tests.<modulo>` para uno solo."
    )
