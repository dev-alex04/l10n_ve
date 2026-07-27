// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

/**
 * Logo de marca Domina, reutilizable en toda la app.
 *
 * El rombo se compone de cuatro cuadrantes, cada uno con su color, tomados del
 * logo oficial (apps/resources/DominaLogo.png). Ojo: domina_isp tiene su propia
 * versión MONOCROMA azul (#1AAEE7, que es casi el cuadrante inferior derecho);
 * son variantes distintas a propósito, no una copia desactualizada.
 *
 * Uso:
 *     l10n_ve.brand.logo_svg()                     // rombo animado, 56px
 *     l10n_ve.brand.logo_svg({size: 24, animated: false})
 *     l10n_ve.brand.loading(__("Generando..."))    // bloque para frappe.dom.freeze
 */

frappe.provide("l10n_ve.brand");

(function () {
	// Un color por cuadrante. Muestreados del PNG, no estimados.
	var COLORS = {
		top_left: "#E91A4B",
		top_right: "#FF5100",
		bottom_right: "#00B5E5",
		bottom_left: "#009B52",
	};

	// Cada path es un cuarto del rombo, cortado en X=0 e Y=0 con 1px de separación.
	var PATHS = {
		top_left: "M -44,-1 L -1,-44 L -1,-26 L -26,-1 Z",
		top_right: "M 1,-44 L 44,-1 L 26,-1 L 1,-26 Z",
		bottom_right: "M 44,1 L 1,44 L 1,26 L 26,1 Z",
		bottom_left: "M -1,44 L -44,1 L -26,1 L -1,26 Z",
	};

	// Orden de despegue de los cuadrantes, en sentido horario.
	var SEQUENCE = ["top_left", "top_right", "bottom_right", "bottom_left"];
	var OFFSETS = {
		top_left: "-6px, -6px",
		top_right: "6px, -6px",
		bottom_right: "6px, 6px",
		bottom_left: "-6px, 6px",
	};

	var STYLE_ID = "l10n-ve-brand-logo-style";

	// La animación se inyecta una sola vez: si fuera parte del markup, cada
	// llamada duplicaría los @keyframes en el DOM.
	function ensure_style() {
		if (document.getElementById(STYLE_ID)) return;

		var rules = [
			".l10nve-brand-part { animation: l10nve-brand-lift 2s ease-in-out infinite; }",
			"@keyframes l10nve-brand-lift {" +
				"0%, 40%, 100% { transform: translate(0, 0); opacity: .85; }" +
				"20% { transform: translate(var(--l10nve-tx), var(--l10nve-ty)); opacity: 1; }" +
				"}",
		];

		SEQUENCE.forEach(function (quadrant, index) {
			var offset = OFFSETS[quadrant].split(", ");
			rules.push(
				".l10nve-brand-" + quadrant.replace("_", "-") + " {" +
					"--l10nve-tx: " + offset[0] + ";" +
					"--l10nve-ty: " + offset[1] + ";" +
					"animation-delay: " + index * 0.5 + "s;" +
					"}",
			);
		});

		var style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = rules.join("\n");
		document.head.appendChild(style);
	}

	l10n_ve.brand.COLORS = COLORS;

	/**
	 * Markup del rombo.
	 * @param {Object} [options]
	 * @param {number} [options.size=56]      lado en píxeles
	 * @param {boolean} [options.animated=true]
	 */
	l10n_ve.brand.logo_svg = function (options) {
		options = options || {};
		var size = options.size || 56;
		var animated = options.animated !== false;

		if (animated) ensure_style();

		var paths = SEQUENCE.map(function (quadrant) {
			var css = animated
				? ' class="l10nve-brand-part l10nve-brand-' + quadrant.replace("_", "-") + '"'
				: "";
			return '<path' + css + ' fill="' + COLORS[quadrant] + '" d="' + PATHS[quadrant] + '" />';
		}).join("");

		return (
			'<svg viewBox="0 0 100 100" width="' + size + '" height="' + size + '" ' +
			'role="img" aria-label="Domina">' +
			'<g transform="translate(50,50)">' + paths + "</g></svg>"
		);
	};

	/**
	 * Bloque de "cargando" listo para ``frappe.dom.freeze()``.
	 * @param {string} message  qué se está haciendo
	 * @param {string} [hint]   aclaración secundaria (p.ej. cuánto puede tardar)
	 */
	l10n_ve.brand.loading = function (message, hint) {
		var extra = hint
			? '<div class="text-muted small">' + frappe.utils.escape_html(hint) + "</div>"
			: "";

		return (
			'<div style="display:flex;flex-direction:column;align-items:center;gap:14px;">' +
			l10n_ve.brand.logo_svg() +
			"<div>" + frappe.utils.escape_html(message || "") + "</div>" +
			extra +
			"</div>"
		);
	};
})();
