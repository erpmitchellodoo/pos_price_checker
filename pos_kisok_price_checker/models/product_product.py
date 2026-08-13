# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _find_product_by_barcode(self, barcode):
        """Find the product matching ``barcode`` (exact or EAN/UPC equivalent).

        Barcode scanners may return either the 12-digit UPC-A or the
        13-digit EAN-13 representation of the same article. When an exact
        match fails, the equivalent encoding is tried as well.

        :param str barcode: barcode scanned by the customer
        :returns: the first matching ``product.product`` or an empty recordset
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return self.browse()

        products = self.env['product.product']
        domain = [('barcode', '=', barcode)]
        product = products.sudo().search(domain, limit=1)
        if product:
            return product

        # 12-digit UPC-A is the same article as the 13-digit EAN-13 that
        # starts with a leading zero (and vice versa).
        if len(barcode) == 12 and barcode.isdigit():
            product = products.sudo().search([('barcode', '=', '0%s' % barcode)], limit=1)
        elif len(barcode) == 13 and barcode.isdigit() and barcode.startswith('0'):
            product = products.sudo().search([('barcode', '=', barcode[1:])], limit=1)

        if not product and _logger.isEnabledFor(logging.INFO):
            _logger.info("No product found for barcode '%s'", barcode)
        return product
