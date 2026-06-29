import frappe
import unittest

def run_suite():
	frappe.connect(site="api.local")
	frappe.db.begin()
	
	try:
		# We must ensure some minimal test records exist if they are loaded by the test
		# But since the tests mock almost everything, they might pass directly!
		from l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.test_ve_fiscal_document_download import TestVEFiscalDocumentDownload
		
		# Load the test suite
		suite = unittest.TestLoader().loadTestsFromTestCase(TestVEFiscalDocumentDownload)
		runner = unittest.TextTestRunner(verbosity=2)
		result = runner.run(suite)
		
		print("\n--- TEST RUN RESULTS ---")
		print(f"Tests run: {result.testsRun}")
		print(f"Errors: {len(result.errors)}")
		print(f"Failures: {len(result.failures)}")
		
		if result.errors or result.failures:
			print("\nErrors/Failures details:")
			for e in result.errors:
				print(f"Error in {e[0]}: {e[1]}")
			for f in result.failures:
				print(f"Failure in {f[0]}: {f[1]}")
			assert False, "Some tests failed!"
		else:
			print("All tests passed successfully!")
			
	except Exception as e:
		import traceback
		traceback.print_exc()
	finally:
		frappe.db.rollback()

if __name__ == "__main__":
	run_suite()
