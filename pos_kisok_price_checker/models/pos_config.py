# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import io
import logging
import re

from odoo import _, api, fields, models
from odoo.addons.http_routing.models.ir_http import slugify
from odoo.exceptions import ValidationError
from odoo.tools import image_data_uri

_logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$')


class PosConfig(models.Model):
    """Extend ``pos.config`` so each store can publish its own price-checker page."""

    _inherit = 'pos.config'

    price_checker_active = fields.Boolean(
        string="Enable Price Checker",
        default=False,
        help="Publish a public, mobile-friendly price-checking page for this store.",
    )
    price_checker_slug = fields.Char(
        string="Price Checker URL Slug",
        copy=False,
        help="Unique URL-safe identifier used in the public price-checker URL "
             "(e.g. https://example.com/price-check/store-a). Leave empty to "
             "generate one automatically from the store name.",
    )
    price_checker_tax_included = fields.Boolean(
        string="Show Tax-Included Price",
        default=True,
        help="Display the price including taxes on the public price-checker page. "
             "If unchecked, the price excluding taxes is displayed.",
    )
    price_checker_pricelist_id = fields.Many2one(
        'product.pricelist',
        string="Price Checker Pricelist",
        ondelete='restrict',
        help="Pricelist used on the public price-checker page. If left empty, "
             "the store's default pricelist is used, or the product's standard "
             "price if the store has no pricelist.",
    )
    price_checker_background_color = fields.Char(
        string="Background Color",
        default='#081849',
        help="Background color of this store's public price-checker page.",
    )
    price_checker_url = fields.Char(
        string="Price Checker URL",
        compute='_compute_price_checker_url',
        help="Public URL customers use to check the price of a product in this store.",
    )
    price_checker_qr_image = fields.Binary(
        string="Price Checker QR Code",
        compute='_compute_price_checker_qr_image',
        attachment=False,
        help="QR code encoding the public price-checker URL of this store. "
             "Print it and display it near the checkout or at the shop entrance.",
    )

    _sql_constraints = [
        (
            'price_checker_slug_uniq',
            'UNIQUE(price_checker_slug)',
            "Another store already uses this Price Checker URL slug. "
            "Please choose a unique slug.",
        ),
    ]

    # ------------------------------------------------------------------
    # Slug handling
    # ------------------------------------------------------------------

    @api.constrains('price_checker_slug')
    def _check_price_checker_slug_format(self):
        for config in self:
            slug = config.price_checker_slug
            if slug and not _SLUG_RE.fullmatch(slug):
                raise ValidationError(_(
                    "The Price Checker URL slug of store %(store)s may only contain "
                    "lowercase letters, digits and hyphens (e.g. 'store-a').",
                    store=config.name,
                ))

    def _check_price_checker_slug_available(self, slug, exclude_id=False):
        """Raise a ``ValidationError`` if another store already uses ``slug``.

        Must be called before the slug is written so the search does not flush
        the new (uncommitted) value into the database.
        """
        if not slug:
            return
        if self.with_context(active_test=False).search_count([
            ('id', '!=', exclude_id),
            ('price_checker_slug', '=', slug),
        ]):
            raise ValidationError(_(
                "Another store already uses this Price Checker URL slug. "
                "Please choose a unique slug.",
            ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            slug = vals.get('price_checker_slug')
            if slug:
                self._check_price_checker_slug_available(str(slug).strip().lower())
        records = super().create(vals_list)
        records._normalize_price_checker()
        return records

    def write(self, vals):
        slug = vals.get('price_checker_slug')
        if slug:
            slug = str(slug).strip().lower()
            for config in self:
                config._check_price_checker_slug_available(slug, config.id)
        res = super().write(vals)
        if any(key in vals for key in ('name', 'price_checker_active', 'price_checker_slug')):
            self._normalize_price_checker()
        return res

    def _normalize_price_checker(self):
        """Keep the slug consistent: lowercased, unique and non-empty for active stores."""
        for config in self:
            slug = config.price_checker_slug
            if slug:
                slug = slug.strip().lower()
            if slug == '':
                slug = False
            if slug and slug != config.price_checker_slug:
                config.price_checker_slug = slug
                slug = config.price_checker_slug

            if config.price_checker_active and not slug:
                base_slug = slugify(config.name or '', max_length=50) or 'store'
                slug = base_slug
                counter = 1
                while self.with_context(active_test=False).search_count([
                    ('id', '!=', config.id),
                    ('price_checker_slug', '=', slug),
                ]):
                    counter += 1
                    slug = '%s-%s' % (base_slug, counter)
                config.price_checker_slug = slug

    # ------------------------------------------------------------------
    # URL / QR helpers
    # ------------------------------------------------------------------

    @api.depends('price_checker_slug')
    def _compute_price_checker_url(self):
        for config in self:
            config.price_checker_url = config._get_price_checker_url()

    @api.depends('price_checker_active', 'price_checker_slug')
    def _compute_price_checker_qr_image(self):
        for config in self:
            if not config.price_checker_active or not config.price_checker_slug:
                config.price_checker_qr_image = False
                continue
            qr_bytes = config._generate_qr_image(config._get_price_checker_url())
            config.price_checker_qr_image = qr_bytes and base64.b64encode(qr_bytes) or False

    @api.model
    def _generate_qr_image(self, value):
        """Return the PNG bytes of a QR code encoding ``value`` or ``False``."""
        if not value:
            return False
        try:
            import qrcode
            import qrcode.constants
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(value)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            return buffer.getvalue()
        except Exception:
            _logger.warning("Could not generate the QR code for '%s'", value, exc_info=True)
            return False

    def _get_price_checker_url(self):
        """Return the public price-checker URL of the store, or ``False``.

        The URL is built from the base URL of the record's website/company so
        that it remains correct when the website is reached through its domain.
        """
        self.ensure_one()
        if not self.price_checker_slug:
            return False
        return '%s/price-check/%s' % (self.get_base_url(), self.price_checker_slug)

    def action_open_price_checker(self):
        self.ensure_one()
        url = self._get_price_checker_url()
        if not url:
            raise ValidationError(_(
                "Store %(store)s has no Price Checker URL yet. Enable the Price "
                "Checker and make sure a URL slug is set.",
                store=self.name,
            ))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Price computation
    # ------------------------------------------------------------------

    def _get_product_price_info(self, product):
        """Compute the store-specific selling information for ``product``.

        The price source follows this priority: the pricelist configured for
        the price-checker page first, then the store's default pricelist (if
        any), then the product's standard price. The resulting unit price is
        converted into the store currency and the product taxes are computed on
        top of it, mirroring what the PoS screen itself would display.

        :param product: a ``product.product`` record
        :returns: dict of display-ready product/price information
        """
        self.ensure_one()
        product.ensure_one()
        company = self.company_id
        store_currency = self.currency_id
        date = fields.Date.today()

        pricelist = self.price_checker_pricelist_id or (
            self.pricelist_id if self.use_pricelist else False
        )
        if pricelist:
            price_unit = pricelist._compute_price_rule(product, 1.0)[product.id][0]
            price_currency = pricelist.currency_id or store_currency
        else:
            price_unit = product.list_price
            price_currency = product.currency_id or company.currency_id
        price_unit = price_currency._convert(price_unit, store_currency, company, date)

        list_price = (product.currency_id or company.currency_id)._convert(
            product.list_price, store_currency, company, date,
        )

        tax_to_use = self.env['account.tax']
        tax_company = company
        while not tax_to_use and tax_company:
            tax_to_use = product.taxes_id.filtered(
                lambda tax: tax.company_id.id == tax_company.id,
            )
            if not tax_to_use:
                tax_company = tax_company.sudo().parent_id

        taxes = tax_to_use.compute_all(price_unit, store_currency, 1.0, product=product)
        price_without_tax = store_currency.round(taxes['total_excluded'])
        price_with_tax = store_currency.round(taxes['total_included'])

        discount = 0.0
        if list_price:
            discount = round((list_price - price_unit) / list_price * 100.0, 2)

        display_price = price_with_tax if self.price_checker_tax_included else price_without_tax
        image_src = False
        if product.image_128:
            # Odoo image fields already contain Base64-encoded image data.
            image_src = image_data_uri(product.image_128)

        return {
            'product_id': product.id,
            'name': product.name,
            'barcode': product.barcode or '',
            'image_src': image_src,
            'uom': product.uom_id.name or '',
            'available_in_pos': product.product_tmpl_id.available_in_pos,
            'price': store_currency.round(display_price),
            'price_without_tax': price_without_tax,
            'price_with_tax': price_with_tax,
            'price_formatted': store_currency.format(display_price),
            'price_without_tax_formatted': store_currency.format(price_without_tax),
            'price_with_tax_formatted': store_currency.format(price_with_tax),
            'list_price': store_currency.round(list_price),
            'list_price_formatted': store_currency.format(list_price),
            'discount': discount,
            'discount_formatted': ('%g' % discount) if discount else '',
            'tax_included': self.price_checker_tax_included,
            'tax_details': [
                {
                    'name': tax['name'],
                    'amount': store_currency.round(tax['amount']),
                    'amount_formatted': store_currency.format(tax['amount']),
                }
                for tax in taxes['taxes']
            ],
            'currency_symbol': store_currency.symbol or '',
            'currency_position': store_currency.position or 'after',
            'pricelist_name': pricelist.name if pricelist else '',
        }
