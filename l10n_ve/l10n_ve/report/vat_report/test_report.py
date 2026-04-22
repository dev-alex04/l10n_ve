import frappe
from l10n_ve.l10n_ve.report.vat_report.vat_report import execute

def test_report():
    filters = {
        "company": "GIO",
        "from_date": "2026-04-01",
        "to_date": "2026-04-30"
    }
    try:
        columns, data, message, chart, report_summary = execute(filters)
        print(f"Data rows: {len(data)}")
        print(f"Summary: {report_summary}")
        if data:
            for row in data:
                print(row)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    test_report()
