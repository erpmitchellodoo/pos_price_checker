# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_BARCODE_LENGTH = 128


class PosPriceChecker(http.Controller):
    """Public, mobile-friendly price checker pages, one per PoS store."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_store(self, slug):
        """Return the active store matching ``slug`` or an empty recordset."""
        if not slug or not isinstance(slug, str):
            return request.env['pos.config']
        slug = slug.strip().lower()
        return request.env['pos.config'].sudo().search([
            ('price_checker_active', '=', True),
            ('price_checker_slug', '=', slug),
        ], limit=1)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @http.route(
        '/price-check/<string:slug>', type='http', auth='public', website=True,
        sitemap=False, readonly=True, methods=['GET'],
    )
    def price_checker_page(self, slug, **kwargs):
        store = self._get_store(slug)
        if not store:
            raise request.not_found()
        return request.render('pos_kisok_price_checker.price_checker_page', {
            'store': store,
        })

    @http.route(
        '/price-check/lookup', type='json', auth='public', website=True,
        methods=['POST'], readonly=True,
    )
    def price_checker_lookup(self, slug=False, barcode=False, **kwargs):
        """Return the store-specific price information for a scanned barcode."""
        store = self._get_store(slug)
        if not store:
            return {'status': 'error', 'message': _(
                "This price checker is not available. Please check the link or "
                "the QR code you used."
            )}

        barcode = (barcode or '').strip()
        if not barcode:
            return {'status': 'error', 'message': _(
                "Please scan or enter a product barcode."
            )}
        if len(barcode) > MAX_BARCODE_LENGTH:
            return {'status': 'error', 'message': _(
                "The barcode you entered is invalid."
            )}

        product = request.env['product.product']._find_product_by_barcode(barcode)
        if not product:
            return {'status': 'not_found', 'message': _(
                "No product was found for barcode %(barcode)s. Please try again.",
                barcode=barcode,
            )}

        return {'status': 'success', 'product': store._get_product_price_info(product)}
