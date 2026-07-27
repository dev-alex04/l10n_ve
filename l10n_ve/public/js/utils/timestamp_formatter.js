/**
 * Sobrescribe la renderización de timestamps globales en Frappe (timeline, comentarios, auditoría)
 * Implementa la Opción 2: Fecha/Hora exacta en formato 12H (DD/MM/YYYY hh:mm A) + tiempo relativo sutil (text-muted).
 */
(function () {
	function format_timestamp_text(datetime, mini) {
		if (!datetime) return "";

		var formatted_date = "";
		if (window.moment) {
			var m = moment(datetime);
			if (m.isValid()) {
				formatted_date = m.format("DD/MM/YYYY hh:mm A");
			}
		}
		if (!formatted_date) {
			formatted_date = frappe.datetime && frappe.datetime.str_to_user
				? frappe.datetime.str_to_user(datetime)
				: datetime;
		}

		var relative = frappe.datetime && frappe.datetime.prettyDate
			? frappe.datetime.prettyDate(datetime, mini)
			: (typeof prettyDate === "function" ? prettyDate(datetime, mini) : "");

		if (formatted_date && relative) {
			return formatted_date + ' <span class="text-muted" style="font-size: 0.9em; opacity: 0.85;">(' + relative + ')</span>';
		} else {
			return formatted_date || relative;
		}
	}

	window.comment_when = function (datetime, mini) {
		if (!datetime) return "";
		var timestamp = frappe.datetime && frappe.datetime.str_to_user
			? frappe.datetime.str_to_user(datetime)
			: datetime;
		var display_html = format_timestamp_text(datetime, mini);

		return (
			'<span class="frappe-timestamp ' +
			(mini ? " mini" : "") +
			'" data-timestamp="' +
			datetime +
			'" title="' +
			timestamp +
			'">' +
			display_html +
			"</span>"
		);
	};

	if (window.frappe) {
		frappe.provide("frappe.datetime");
		frappe.datetime.comment_when = window.comment_when;

		frappe.datetime.refresh_when = function () {
			if (window.jQuery) {
				$(".frappe-timestamp").each(function () {
					var dt = $(this).attr("data-timestamp");
					if (!dt) return;
					var mini = $(this).hasClass("mini");
					$(this).html(format_timestamp_text(dt, mini));
				});
			}
		};
	}
})();
