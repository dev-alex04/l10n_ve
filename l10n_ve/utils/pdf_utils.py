import re
import os
import glob
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
    wkhtmltopdf to fail with HostNotFoundError in isolated environments.
    Also inline local CSS stylesheets to prevent network deadlocks,
    and resolve local relative images to verify they exist on disk."""

    # 1. Process stylesheet <link> tags
    link_pattern = r'<link\b[^>]*>'
    def replace_link(match):
        tag = match.group(0)
        # Check if it's a stylesheet
        href_match = re.search(r'href=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if not href_match:
            return tag

        href = href_match.group(1)

        # Check if external stylesheet
        is_external = any(domain in href for domain in _EXTERNAL_DOMAINS) or \
                      (href.startswith(("http://", "https://", "//")) and not any(h in href for h in ("localhost", "127.0.0.1", "api.local")))

        if is_external:
            return ""  # strip it

        # If it's a stylesheet link, try to inline it
        is_stylesheet = "stylesheet" in tag.lower() or href.lower().endswith(".css") or ".css?" in href.lower()
        if is_stylesheet:
            clean_href = href
            if "assets/" in href:
                assets_idx = href.find("assets/")
                clean_href = "/" + href[assets_idx:]

            if clean_href.startswith("/assets/"):
                rel_path = clean_href.lstrip("/")
                abs_path = os.path.join(frappe.local.sites_path, rel_path)

                # If exact file doesn't exist, try to match by glob (wildcard the hash)
                if not os.path.exists(abs_path):
                    directory, filename = os.path.split(abs_path)
                    base, ext = os.path.splitext(filename)
                    parts = base.split('.')
                    if len(parts) > 1:
                        # Replace the last element (the hash) with '*'
                        pattern = '.'.join(parts[:-1]) + '.*' + ext
                        matches = glob.glob(os.path.join(directory, pattern))
                        if matches:
                            abs_path = matches[0]

                if os.path.exists(abs_path):
                    try:
                        with open(abs_path, 'r', encoding='utf-8') as f:
                            css_content = f.read()
                        return f"<style>{css_content}</style>"
                    except Exception:
                        pass

            # If we couldn't resolve or read it, return empty string to prevent network request deadlock
            return ""

        return tag

    html = re.sub(link_pattern, replace_link, html, flags=re.IGNORECASE)

    # 2. Remove <script src="https://external..."></script>
    def remove_external_script(match):
        tag = match.group(0)
        if any(domain in tag for domain in _EXTERNAL_DOMAINS):
            return ""
        return tag

    html = re.sub(r'<script\b[^>]*src=[^>]*>.*?</script>', remove_external_script,
                  html, flags=re.IGNORECASE | re.DOTALL)

    # 3. Resolve local relative images and check existence
    img_pattern = r'<img\b[^>]*src=["\']([^"\']*)["\'][^>]*>'
    def replace_img(match):
        tag = match.group(0)
        src = match.group(1)
        if src.startswith("/files/"):
            file_rel_path = src.lstrip("/")
            try:
                public_path = frappe.get_site_path("public")
                full_path = os.path.join(public_path, file_rel_path)
                if not os.path.exists(full_path):
                    # Fallback to galanet_logo.jpg
                    fallback_path = os.path.join(public_path, "files", "galanet_logo.jpg")
                    if os.path.exists(fallback_path):
                        return tag.replace(src, "/files/galanet_logo.jpg")
                    else:
                        return tag.replace(src, "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
            except Exception:
                pass
        return tag

    html = re.sub(img_pattern, replace_img, html, flags=re.IGNORECASE)
    return html



@frappe.whitelist()
def custom_report_to_pdf(html, orientation="Landscape"):
	"""Custom report_to_pdf that handles proxy/DNS issues with wkhtmltopdf.

	wkhtmltopdf may fail to resolve the server's own hostname (e.g. api.local)
	when loading CSS/images embedded in the HTML. This function tries multiple
	strategies to generate the PDF successfully.
	"""
	try:
		# Truncate HTML page field to avoid MySQL max_allowed_packet / connection reset errors on large reports
		safe_page = html[:50000] if html else None
		make_access_log(file_type="PDF", method="PDF", page=safe_page)
	except Exception:
		# If log insertion fails, do not block PDF generation
		pass

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

	# Strategy 2: With explicit proxy bypass for local and server hostnames
	try:
		from urllib.parse import urlparse
		bypass_hosts = {"127.0.0.1", "localhost", "api.local"}
		for allow_header in (True, False):
			try:
				h = urlparse(frappe.utils.get_url(allow_header_override=allow_header)).hostname
				if h:
					bypass_hosts.add(h)
			except Exception:
				pass

		frappe.local.response.filecontent = get_pdf(
			html,
			{
				"orientation": orientation,
				"proxy": "http://0.0.0.0:0",
				"bypass-proxy-for": list(bypass_hosts),
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

