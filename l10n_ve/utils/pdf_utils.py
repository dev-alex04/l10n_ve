import re
import frappe
from frappe.utils.pdf import get_pdf
from frappe.core.doctype.access_log.access_log import make_access_log


# Domains that wkhtmltopdf cannot resolve inside WSL / isolated networks
_EXTERNAL_DOMAINS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "ajax.googleapis.com",
)


def _sanitize_html_for_wkhtmltopdf(html):
    """Remove external <link> and <script src> tags that would cause
    wkhtmltopdf to fail with HostNotFoundError in isolated environments."""
    # Remove <link ...href="https://external..." ...> tags
    def remove_external_link(match):
        tag = match.group(0)
        if any(domain in tag for domain in _EXTERNAL_DOMAINS):
            return ""  # strip it
        return tag

    html = re.sub(r'<link\b[^>]*>', remove_external_link, html, flags=re.IGNORECASE)
    # Remove <script src="https://external..."></script>
    def remove_external_script(match):
        tag = match.group(0)
        if any(domain in tag for domain in _EXTERNAL_DOMAINS):
            return ""
        return tag

    html = re.sub(r'<script\b[^>]*src=[^>]*>.*?</script>', remove_external_script,
                  html, flags=re.IGNORECASE | re.DOTALL)
    return html


@frappe.whitelist()
def custom_report_to_pdf(html, orientation="Landscape"):
	"""Custom report_to_pdf that handles proxy/DNS issues with wkhtmltopdf.

	wkhtmltopdf may fail to resolve the server's own hostname (e.g. api.local)
	when loading CSS/images embedded in the HTML. This function tries multiple
	strategies to generate the PDF successfully.
	"""
	make_access_log(file_type="PDF", method="PDF", page=html)
	frappe.local.response.filename = "report.pdf"

	# Strip external resource links (Google Fonts, CDNs, etc.)
	# that cause HostNotFoundError in isolated/WSL environments
	html = _sanitize_html_for_wkhtmltopdf(html)


	# Strategy 1: Simple call with load-error-handling skip
	try:
		frappe.local.response.filecontent = get_pdf(
			html,
			{
				"orientation": orientation,
				"load-error-handling": "skip",
				"no-stop-slow-scripts": "",
				"disable-javascript": "",
			},
		)
		frappe.local.response.type = "pdf"
		return
	except Exception:
		pass

	# Strategy 2: With explicit proxy bypass for the server's own hostname
	try:
		from urllib.parse import urlparse

		hostname = urlparse(frappe.utils.get_url(allow_header_override=False)).hostname
		frappe.local.response.filecontent = get_pdf(
			html,
			{
				"orientation": orientation,
				"proxy": "http://0.0.0.0:0",
				"bypass-proxy-for": hostname,
				"load-error-handling": "skip",
				"no-stop-slow-scripts": "",
				"disable-javascript": "",
			},
		)
		frappe.local.response.type = "pdf"
		return
	except Exception:
		pass

	# Strategy 3: Bare minimum options as last resort
	try:
		frappe.local.response.filecontent = get_pdf(
			html,
			{
				"orientation": orientation,
			},
		)
		frappe.local.response.type = "pdf"
		return
	except Exception as e:
		frappe.log_error(
			title="Custom PDF Print Final Error",
			message=f"All PDF generation strategies failed:\n{frappe.get_traceback()}"
		)
		raise e


def safe_get_pdf(html, options=None):
	"""Wrapper around get_pdf that handles common wkhtmltopdf failures.

	Use this in impression files instead of calling get_pdf directly.
	"""
	if options is None:
		options = {}

	# Strip external resource links before generating PDF
	html = _sanitize_html_for_wkhtmltopdf(html)

	# Ensure resilient defaults
	options.setdefault("load-error-handling", "skip")
	options.setdefault("no-stop-slow-scripts", "")
	options.setdefault("disable-javascript", "")

	try:
		return get_pdf(html, options)
	except OSError as e:
		if any(err in str(e) for err in ("ConnectionRefusedError", "Exit with code 1", "HostNotFoundError")):
			# Retry with minimal options
			minimal_options = {"orientation": options.get("orientation", "Portrait")}
			try:
				return get_pdf(html, minimal_options)
			except Exception as ex:
				frappe.log_error(
					title="PDF Generation Retry Error",
					message=f"safe_get_pdf retry failed:\n{frappe.get_traceback()}"
				)
				raise ex
		raise e

