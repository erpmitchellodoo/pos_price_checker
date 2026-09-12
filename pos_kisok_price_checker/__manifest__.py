{
    'name': 'POS KISOK PRICE CHECKER',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Mobile-friendly website price checker per POS store',
    'description': """
pos_kisok_price_checker
=======================

Give every PoS store its own public, mobile-friendly price-checking page
(``/price-check/<slug>``) where customers scan a product barcode with their
phone camera and instantly see the selling price applicable to that store.

Main features
-------------

* One public URL + QR code per store, generated from the store form
  (e.g. ``https://example.com/price-check/store-a``).
* In-browser barcode scanning (Shape Detection ``BarcodeDetector`` API with a
  ZXing fallback) plus a manual barcode entry field for devices without a
  camera.
* Store-specific pricing: the PoS store's default pricelist is used to compute
  the displayed price, converted into the store currency and shown either
  including or excluding taxes, as configured on the store.
* EAN-13 / UPC-A cross-encoding lookup, product image, tax breakdown and
  discount indicator on the result card.
* No dedicated kiosk hardware required: any smartphone with a camera works.

Configuration
-------------

1. Point of Sale > Configuration, open a PoS store and switch to the
   "Price Checker" tab.
2. Tick *Enable Price Checker*. A public URL slug is generated automatically
   from the store name and you can edit it afterwards (e.g. ``store-a``).
3. Choose whether the displayed price includes taxes
   (*Tax-Included Price*).
4. Optional: restrict the page to a specific price list by adding a
   *Pricelist* row. The priority is: kiosk pricelist > store default
   pricelist > standard price.
5. Save the store. The public URL and a ready-to-print *QR code* are generated
   and shown on the same tab — print it and place it on the shelves or at the
   checkout counter.
6. Customers scan the code with any phone camera and land on the store's
   price-checker page.

Requirements
------------

* Python ``qrcode`` library (``pip install qrcode``) is used to render the
  QR codes; the public page itself needs nothing but a browser with a camera.
""",
    "author": "Mitchel Admin",
    "maintainer": "Mitchel Admin",
    "support": "erpmitchellodoo@gmail.com",
    'website': '',
    'license': 'LGPL-3',
    'images': [
        'static/description/appstore_banner_screenshot.png',
        'static/description/price_checker_scan_screenshot.png',
        'static/description/price_checker_result_screenshot.png',
        'static/description/price_checker_configuration_screenshot.png',
    ],
    'depends': ['base', 'point_of_sale', 'barcodes', 'website'],
    'data': [
        'views/pos_config_views.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'pos_kisok_price_checker/static/src/scss/price_checker.scss',
            'pos_kisok_price_checker/static/src/xml/price_checker_templates.xml',
            'pos_kisok_price_checker/static/src/js/price_checker.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
