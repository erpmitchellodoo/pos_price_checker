/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import {
    BarcodeVideoScanner,
    isBarcodeScannerSupported,
} from "@web/core/barcode/barcode_video_scanner";

/**
 * Public price checker used on /price-check/<slug> pages.
 *
 * Scans product barcodes with the phone camera (BarcodeDetector API or ZXing
 * fallback), queries the store-specific price and displays the result.
 */
export class PriceChecker extends Component {
    static template = "pos_kisok_price_checker.PriceChecker";
    static components = { BarcodeVideoScanner };
    static props = {
        slug: { type: String },
        taxIncluded: { type: Boolean, optional: true },
    };
    static defaultProps = {
        taxIncluded: true,
    };

    setup() {
        this.state = useState({
            screen: "idle", // idle | camera | loading | success | not_found | error
            scannerSupported: isBarcodeScannerSupported(),
            scannerReady: false,
            manualBarcode: "",
            lastBarcode: "",
            product: null,
            message: "",
        });
    }

    // ------------------------------------------------------------------
    // Scanner
    // ------------------------------------------------------------------

    startScanner() {
        this.state.lastBarcode = "";
        this.state.scannerReady = false;
        this.state.screen = "camera";
    }

    stopScanner() {
        this.state.screen = "idle";
    }

    onScannerReady() {
        this.state.scannerReady = true;
    }

    onBarcodeDetected(barcode) {
        // The camera keeps scanning continuously; ignore re-detections of the
        // same code to avoid spamming the server while a result is shown.
        if (!barcode || barcode === this.state.lastBarcode) {
            return;
        }
        this.state.lastBarcode = barcode;
        this.lookup(barcode);
    }

    onScannerError(error) {
        this.state.screen = "error";
        this.state.message = error.message || _t("Could not start the camera.");
    }

    // ------------------------------------------------------------------
    // Lookup
    // ------------------------------------------------------------------

    async lookup(barcode) {
        barcode = (barcode || "").trim();
        if (!barcode) {
            return;
        }
        this.state.screen = "loading";
        this.state.product = null;
        this.state.message = "";
        try {
            const result = await rpc("/price-check/lookup", {
                slug: this.props.slug,
                barcode,
            });
            if (result.status === "success") {
                this.state.screen = "success";
                this.state.product = result.product;
            } else if (result.status === "not_found") {
                this.state.screen = "not_found";
                this.state.message = result.message;
            } else {
                this.state.screen = "error";
                this.state.message = result.message;
            }
        } catch (error) {
            this.state.screen = "error";
            this.state.message = error.message || _t("Something went wrong. Please try again.");
        }
    }

    scanAnother() {
        this.state.lastBarcode = "";
        this.state.product = null;
        this.state.message = "";
        this.state.screen = this.state.scannerReady ? "camera" : "idle";
    }

    async onManualSubmit() {
        const barcode = this.state.manualBarcode.trim();
        if (!barcode) {
            this.state.screen = "error";
            this.state.message = _t("Please enter a barcode.");
            return;
        }
        this.state.manualBarcode = "";
        this.lookup(barcode);
    }
}

registry.category("public_components").add("pos_kisok_price_checker.PriceChecker", PriceChecker);
