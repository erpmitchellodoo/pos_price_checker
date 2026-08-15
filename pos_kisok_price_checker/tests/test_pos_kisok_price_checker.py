# Part of Odoo. See LICENSE file for full copyright and licensing details.

import uuid

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


def _next_cash_code():
    counter = getattr(_next_cash_code, '_counter', 0) + 1
    _next_cash_code._counter = counter
    return counter


def _unique_code():
    # account.journal.code is limited to 5 characters and must be unique per
    # company, so use a short random suffix instead of a predictable counter.
    return 'PC' + uuid.uuid4().hex[:3]


@tagged('post_install', '-at_install')
class TestPosPriceCheckerModel(TestPoSCommon):
    """Model-level tests: slug generation, price computation."""

    def setUp(self):
        super().setUp()
        self.product = self.create_product(
            'Price Checker Product', self.categ_basic, lst_price=100.0)
        self.product.barcode = '1234567890123'
        self.pricelist_10 = self.env['product.pricelist'].create({
            'name': 'PC 10% off',
            'currency_id': self.company_currency.id,
            'item_ids': [Command.create({
                'compute_price': 'percentage',
                'percent_price': 10,
            })],
        })
        self.pricelist_20 = self.env['product.pricelist'].create({
            'name': 'PC 20% off',
            'currency_id': self.company_currency.id,
            'item_ids': [Command.create({
                'compute_price': 'percentage',
                'percent_price': 20,
            })],
        })
        self.tax_15 = self.env['account.tax'].create({
            'name': 'PC Tax 15%',
            'amount': 15,
        })

    def _new_cash_payment_method(self):
        n = _next_cash_code()
        journal = self.env['account.journal'].create({
            'name': 'Cash %d' % n,
            'type': 'cash',
            'code': _unique_code(),
            'company_id': self.env.company.id,
        })
        return self.env['pos.payment.method'].create({
            'name': 'Cash %d' % n,
            'journal_id': journal.id,
            'receivable_account_id': self.pos_receivable_cash.id,
            'company_id': self.env.company.id,
        })

    def _create_store(self, name='Store A', pricelist=False, tax_included=True,
                      kiosk_pricelist=False):
        vals = {
            'name': name,
            'journal_id': self.invoice_journal.id,
            'invoice_journal_id': self.invoice_journal.id,
            'payment_method_ids': [(6, 0, self._new_cash_payment_method().ids)],
            'price_checker_tax_included': tax_included,
            'price_checker_active': True,
        }
        if pricelist:
            vals.update({
                'use_pricelist': True,
                'pricelist_id': pricelist.id,
                'available_pricelist_ids': [(6, 0, pricelist.ids)],
            })
        if kiosk_pricelist:
            vals['price_checker_pricelist_id'] = kiosk_pricelist.id
        return self.env['pos.config'].create(vals)

    def test_slug_auto_generation(self):
        store = self._create_store()
        self.assertEqual(store.price_checker_slug, 'store-a')
        store2 = self._create_store(name='Store A')
        self.assertEqual(store2.price_checker_slug, 'store-a-2')

    def test_slug_format_constraint(self):
        store = self._create_store()
        with self.assertRaises(ValidationError):
            store.price_checker_slug = 'Store A!'
            store.flush_recordset()

    def test_slug_unique_constraint(self):
        store = self._create_store()
        store2 = self._create_store(name='Store B')
        with self.assertRaises(ValidationError):
            store2.price_checker_slug = 'store-a'
            store2.flush_recordset()

    def test_price_checker_url(self):
        store = self._create_store()
        self.assertTrue(store._get_price_checker_url().endswith('/price-check/store-a'))

    def test_price_with_pricelist(self):
        store = self._create_store(pricelist=self.pricelist_10)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['list_price'], 100.0)
        self.assertEqual(info['price'], 90.0)
        self.assertEqual(info['discount'], 10.0)
        self.assertEqual(info['tax_included'], True)
        # res.currency.format() inserts a non-breaking space between the
        # symbol and the amount.
        self.assertEqual(info['price_formatted'].replace('\xa0', ''), '$90.00')

    def test_price_tax_excluded(self):
        store = self._create_store(pricelist=self.pricelist_10, tax_included=False)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 90.0)
        self.assertEqual(info['tax_included'], False)

    def test_price_without_pricelist(self):
        store = self._create_store()
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 100.0)
        self.assertEqual(info['discount'], 0.0)

    def test_kiosk_pricelist_overrides_store_pricelist(self):
        store = self._create_store(
            pricelist=self.pricelist_10, kiosk_pricelist=self.pricelist_20)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 80.0)
        self.assertEqual(info['pricelist_name'], self.pricelist_20.name)

    def test_kiosk_pricelist_falls_back_to_store_pricelist(self):
        store = self._create_store(pricelist=self.pricelist_10)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 90.0)
        self.assertEqual(info['pricelist_name'], self.pricelist_10.name)

    def test_kiosk_pricelist_falls_back_to_standard_price(self):
        store = self._create_store(kiosk_pricelist=False)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 100.0)
        self.assertEqual(info['pricelist_name'], '')

    def test_price_with_tax_on_product(self):
        self.product.taxes_id = [(6, 0, self.tax_15.ids)]
        store = self._create_store(pricelist=self.pricelist_10)
        info = store._get_product_price_info(self.product)
        self.assertEqual(info['price'], 103.5)
        self.assertEqual(len(info['tax_details']), 1)

    def test_find_product_by_barcode(self):
        self.assertEqual(
            self.product._find_product_by_barcode('1234567890123').id,
            self.product.id)
        self.assertFalse(self.product._find_product_by_barcode('0000000000000'))

    def test_find_product_by_barcode_upc_ean_crossmatch(self):
        product_ean = self.env['product.product'].create({
            'name': 'EAN product',
            'lst_price': 10.0,
            'barcode': '0123456789012',
            'available_in_pos': True,
        })
        self.assertEqual(
            product_ean._find_product_by_barcode('123456789012').id,
            product_ean.id)
        self.assertEqual(
            product_ean._find_product_by_barcode('0123456789012').id,
            product_ean.id)


@tagged('post_install', '-at_install')
class TestPosPriceCheckerRoutes(HttpCase):
    """HTTP tests: public page and JSON-RPC lookup route."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.groups_id += cls.env.ref('point_of_sale.group_pos_manager')
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id

        cls.pricelist_10 = cls.env['product.pricelist'].create({
            'name': 'PC 10% off',
            'currency_id': cls.company_currency.id,
            'item_ids': [Command.create({
                'compute_price': 'percentage',
                'percent_price': 10,
            })],
        })
        cls.pricelist_20 = cls.env['product.pricelist'].create({
            'name': 'PC 20% off',
            'currency_id': cls.company_currency.id,
            'item_ids': [Command.create({
                'compute_price': 'percentage',
                'percent_price': 20,
            })],
        })

        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale')], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Price Checker Sales',
                'type': 'sale',
                'code': 'PCSALE',
                'company_id': cls.company.id,
            })
        cls.pos_receivable_cash = cls.env['account.account'].create({
            'name': 'Price Checker Receivable',
            'code': _unique_code(),
            'account_type': 'asset_receivable',
            'reconcile': True,
        })

        def _new_cash_payment_method():
            n = _next_cash_code()
            journal = cls.env['account.journal'].create({
                'name': 'Cash %d' % n,
                'type': 'cash',
                'code': _unique_code(),
                'company_id': cls.company.id,
            })
            return cls.env['pos.payment.method'].create({
                'name': 'Cash %d' % n,
                'journal_id': journal.id,
                'receivable_account_id': cls.pos_receivable_cash.id,
                'company_id': cls.company.id,
            })

        def _store(name, pricelist):
            return cls.env['pos.config'].create({
                'name': name,
                'journal_id': cls.sale_journal.id,
                'invoice_journal_id': cls.sale_journal.id,
                'payment_method_ids': [(6, 0, _new_cash_payment_method().ids)],
                'use_pricelist': True,
                'pricelist_id': pricelist.id,
                'available_pricelist_ids': [(6, 0, pricelist.ids)],
                'price_checker_tax_included': True,
                'price_checker_active': True,
            })

        cls.store_a = _store('Store A', cls.pricelist_10)
        cls.store_b = _store('Store B', cls.pricelist_20)

        cls.product = cls.env['product.product'].create({
            'name': 'HTTP Test Product',
            'lst_price': 100.0,
            'barcode': '1234567890123',
            'available_in_pos': True,
            # Odoo 17 defaults new products to the company's sale tax.
            'taxes_id': [Command.clear()],
            'company_id': cls.company.id,
        })

        if not cls.env['website'].search([], limit=1):
            cls.env['website'].create({'name': 'Price Checker Website'})

    def test_price_checker_page(self):
        resp = self.url_open('/price-check/store-a')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Store A', resp.text)

    def test_price_checker_page_unknown_store(self):
        resp = self.url_open('/price-check/does-not-exist')
        self.assertEqual(resp.status_code, 404)

    def test_lookup_success(self):
        result = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-a',
            'barcode': '1234567890123',
        })
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['product']['barcode'], '1234567890123')
        self.assertEqual(result['product']['price'], 90.0)
        self.assertTrue(result['product']['available_in_pos'])

    def test_lookup_per_store_price(self):
        store_a = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-a',
            'barcode': '1234567890123',
        })['product']
        store_b = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-b',
            'barcode': '1234567890123',
        })['product']
        self.assertEqual(store_a['price'], 90.0)
        self.assertEqual(store_b['price'], 80.0)
        self.assertNotEqual(store_a['price'], store_b['price'])

    def test_lookup_not_found(self):
        result = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-a',
            'barcode': '0000000000000',
        })
        self.assertEqual(result['status'], 'not_found')

    def test_lookup_unknown_store(self):
        result = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'does-not-exist',
            'barcode': '1234567890123',
        })
        self.assertEqual(result['status'], 'error')

    def test_lookup_missing_barcode(self):
        result = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-a',
        })
        self.assertEqual(result['status'], 'error')

    def test_lookup_disabled_store(self):
        self.store_a.price_checker_active = False
        result = self.make_jsonrpc_request('/price-check/lookup', {
            'slug': 'store-a',
            'barcode': '1234567890123',
        })
        self.assertEqual(result['status'], 'error')
