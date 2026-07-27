# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la selección del PDF fiscal cacheado en
l10n_ve.digital_invoice.tfhka_client.get_fiscal_invoice_pdf.

A una factura se le adjuntan, además del PDF fiscal que baja de HKA, los
comprobantes de retención de IVA/ISLR que carga el usuario (campos Attach
voucher_image / voucher_image_islr). Todos cuelgan del mismo documento, así que
una búsqueda por "%.pdf" los mezcla y —al servirse el más reciente— la vista
previa terminaba mostrando la retención en lugar de la factura. La búsqueda debe
acotarse al prefijo con el que este mismo módulo guarda el PDF fiscal.

Suite 100% unittest + mocks (sin BD ni FrappeTestCase): el módulo solo importa
frappe a nivel top-level, así que se importa sin arrancar el site.
"""

import base64
import json
import re
import unittest
from unittest.mock import MagicMock, patch

from l10n_ve.digital_invoice import tfhka_client
from l10n_ve.digital_invoice.tfhka_client import (
    FISCAL_PDF_LIKE_PATTERN,
    FISCAL_PDF_PREFIX,
    get_fiscal_invoice_pdf,
)

INVOICE = "ACC-SINV-2026-12924-1"
VAT_VOUCHER = "ACC-VATWH-2026-00133"

HKA_REMARKS = json.dumps({
    "resultado": {
        "serie": "MIR-01",
        "numeroDocumento": "2900",
        "numeroControl": "00-00233094",
        "urlConsulta": "https://demo.imprentadigital.com/consulta/x",
    },
    "codigo": "200",
})

FACTURA_PDF = b"%PDF-1.4 factura fiscal"
FACTURA_REEMITIDA_PDF = b"%PDF-1.4 factura fiscal reemitida"
RETENCION_PDF = b"%PDF-1.4 comprobante de retencion"
VOUCHER_PDF = b"%PDF-1.4 comprobante fiscal de retencion emitido por HKA"

# Adjuntos tal como quedan en la práctica: las retenciones se cargan días después
# de la certificación, así que son las más recientes por `creation`.
ATTACHMENTS = [
    {"name": "FILE-ret-islr", "file_name": "20260700018932.pdf",
     "creation": "2026-07-20 10:00:00"},
    {"name": "FILE-ret-iva", "file_name": "19914.pdf",
     "creation": "2026-07-18 09:00:00"},
    {"name": "FILE-factura", "file_name": f"{FISCAL_PDF_PREFIX}{INVOICE}_2900.pdf",
     "creation": "2026-07-01 08:00:00"},
]

# Reemisión (p. ej. tras un 201 duplicado): queda una segunda factura adjunta, más
# nueva que la original pero más vieja que las retenciones cargadas después.
REEMISION = {"name": "FILE-factura-reemitida",
             "file_name": f"{FISCAL_PDF_PREFIX}{INVOICE}_2901.pdf",
             "creation": "2026-07-15 12:00:00"}

CONTENIDOS = {
    "FILE-ret-islr": RETENCION_PDF,
    "FILE-ret-iva": RETENCION_PDF,
    "FILE-factura": FACTURA_PDF,
    "FILE-factura-reemitida": FACTURA_REEMITIDA_PDF,
    "FILE-voucher": VOUCHER_PDF,
}


def _matches(pattern: str, file_name: str) -> bool:
    """Semántica de LIKE de SQL: % = cualquier cosa, _ = un carácter."""
    regex = "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in pattern
    )
    return re.match(f"^{regex}$", file_name) is not None


class TestFiscalPdfLikePattern(unittest.TestCase):
    """El patrón debe distinguir el PDF fiscal de los adjuntos del usuario."""

    def test_pattern_matches_generated_filename(self):
        generado = f"{FISCAL_PDF_PREFIX}{INVOICE}_2900.pdf"
        self.assertTrue(_matches(FISCAL_PDF_LIKE_PATTERN, generado))

    def test_pattern_rejects_retention_filenames(self):
        # Nombres reales de comprobantes de retención cargados en producción.
        for nombre in (
            "19914.pdf",
            "20260700018932.pdf",
            "comprobante.pdf",
            "RET. ISLR FACT 226063 GALANET SOLUTION.pdf",
            "Galanet Solution, C.A. Factura 226115 Retencion ISLR.pdf",
            "PAGO FACT226022, RET IVA E ISLR GALANET.pdf",
        ):
            with self.subTest(nombre=nombre):
                self.assertFalse(_matches(FISCAL_PDF_LIKE_PATTERN, nombre))

    def test_pattern_is_not_backslash_escaped(self):
        """Escapar el guion bajo rompe el filtro en silencio (devuelve 0 filas)."""
        self.assertNotIn("\\", FISCAL_PDF_LIKE_PATTERN)
        self.assertTrue(FISCAL_PDF_LIKE_PATTERN.startswith(FISCAL_PDF_PREFIX))


class TestGetFiscalInvoicePdfCache(unittest.TestCase):
    """La consulta de caché no debe poder alcanzar un comprobante de retención."""

    def _run(self, attachments, doctype="Sales Invoice", docname=INVOICE):
        """Ejecuta el endpoint con la capa de Frappe mockeada y devuelve
        (resultado, kwargs con los que se consultó el doctype File)."""
        captured = {}

        doc = MagicMock()
        if doctype in ("VAT Withholding Voucher", "ISLR Withholding Voucher"):
            doc.hka_response = HKA_REMARKS
        else:
            doc.remarks = HKA_REMARKS

        def fake_get_all(queried_doctype, **kwargs):
            captured["doctype"] = queried_doctype
            captured.update(kwargs)
            pattern = kwargs["filters"]["file_name"][1]
            rows = [a for a in attachments if _matches(pattern, a["file_name"])]
            # Replicar el order_by real: el resto de la función asume que [0] es
            # el vigente, así que ordenar aquí es parte de lo que se está probando.
            if kwargs.get("order_by") == "creation desc":
                rows.sort(key=lambda a: a["creation"], reverse=True)
            return rows

        def fake_get_doc(file_doctype, name):
            file_doc = MagicMock()
            file_doc.get_content.return_value = CONTENIDOS[name]
            return file_doc

        with patch.object(tfhka_client.frappe, "get_cached_doc", return_value=doc), \
             patch.object(tfhka_client.frappe, "has_permission", return_value=True), \
             patch.object(tfhka_client.frappe, "get_all", side_effect=fake_get_all), \
             patch.object(tfhka_client.frappe, "get_doc", side_effect=fake_get_doc), \
             patch.object(tfhka_client, "TFHKAClient") as client_cls:
            # Si la caché fallara, el test no debe salir a la red: que se note.
            client_cls.side_effect = AssertionError("no debe descargarse de HKA")
            result = get_fiscal_invoice_pdf(docname, doctype)

        return result, captured

    def test_serves_invoice_pdf_not_retention(self):
        result, _ = self._run(ATTACHMENTS)
        self.assertEqual(base64.b64decode(result["base64"]), FACTURA_PDF)

    def test_query_filters_by_fiscal_prefix(self):
        _, captured = self._run(ATTACHMENTS)
        self.assertEqual(captured["doctype"], "File")
        self.assertEqual(captured["filters"]["attached_to_doctype"], "Sales Invoice")
        self.assertEqual(captured["filters"]["attached_to_name"], INVOICE)
        self.assertEqual(
            captured["filters"]["file_name"], ["like", FISCAL_PDF_LIKE_PATTERN]
        )

    def test_keeps_latest_emission_first(self):
        """Invariante de reemisión: tras un 201 duplicado el vigente es el nuevo,
        aunque haya retenciones adjuntadas después que él."""
        result, captured = self._run(ATTACHMENTS + [REEMISION])
        self.assertEqual(captured["order_by"], "creation desc")
        self.assertEqual(base64.b64decode(result["base64"]), FACTURA_REEMITIDA_PDF)

    def test_only_retentions_attached_falls_back_to_hka(self):
        """Sin PDF fiscal cacheado hay que bajarlo, no servir la retención."""
        solo_retenciones = [a for a in ATTACHMENTS if a["name"] != "FILE-factura"]
        with self.assertRaises(AssertionError):
            self._run(solo_retenciones)

    def test_withholding_voucher_still_finds_its_own_pdf(self):
        """El endpoint también sirve los comprobantes de retención como documento
        propio (lee hka_response). Su PDF se guarda con el mismo prefijo, así que
        el filtro no puede dejarlos sin caché."""
        adjuntos = [
            {"name": "FILE-voucher",
             "file_name": f"{FISCAL_PDF_PREFIX}{VAT_VOUCHER}_20260700018932.pdf",
             "creation": "2026-07-10 11:00:00"},
        ]
        result, captured = self._run(
            adjuntos, doctype="VAT Withholding Voucher", docname=VAT_VOUCHER
        )
        self.assertEqual(captured["filters"]["attached_to_doctype"],
                         "VAT Withholding Voucher")
        self.assertEqual(base64.b64decode(result["base64"]), VOUCHER_PDF)


if __name__ == "__main__":
    unittest.main()
