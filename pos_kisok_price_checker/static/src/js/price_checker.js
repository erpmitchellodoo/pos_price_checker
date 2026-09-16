/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
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
        this.root = useRef("root");
        this.barcodeInput = useRef("barcodeInput");
        this.lookupSequence = 0;
        onWillUnmount(() => this.lookupSequence++);
        onMounted(() => {
            const page = this.root.el.closest(".pos_kisok_price_checker_page");
            if (!page) {
                return;
            }
            // The browser normalizes the configured color to RGB, including named colors.
            const channels = getComputedStyle(page).backgroundColor.match(/[\d.]+/g).map(Number);
            const alpha = channels[3] ?? 1;
            const linear = channels.slice(0, 3).map((channel) => {
                const value = (channel * alpha + 255 * (1 - alpha)) / 255;
                return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
            });
            const luminance = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
            // Prefer slate when it meets 4.5:1; otherwise choose white or black.
            const color = (luminance + 0.05) / (0.00919 + 0.05) >= 4.5
                ? "#0f172a"
                : 1.05 / (luminance + 0.05) >= 4.5 ? "#ffffff" : "#000000";
            page.style.setProperty("--price-checker-brand-color", color);
        });
        this.state = useState({
            screen: "idle", // idle | camera | loading | success | not_found | error
            scannerSupported: isBarcodeScannerSupported(),
            scannerReady: false,
            manualBarcode: "",
            lastBarcode: "",
            product: null,
            message: "",
        });
        useEffect(() => {
            if (["idle", "success", "not_found", "error"].includes(this.state.screen)) {
                this.barcodeInput.el?.focus({ preventScroll: true });
            }
            if (this.state.screen === "success") {
                const timer = setTimeout(() => this.resetToIdle(), 15000);
                return () => clearTimeout(timer);
            }
        }, () => [this.state.screen, this.state.product]);
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
        const sequence = ++this.lookupSequence;
        this.state.screen = "loading";
        this.state.product = null;
        this.state.message = "";
        try {
            const result = await rpc("/price-check/lookup", {
                slug: this.props.slug,
                barcode,
            });
            if (sequence !== this.lookupSequence) {
                return;
            }
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
            if (sequence !== this.lookupSequence) {
                return;
            }
            this.state.screen = "error";
            this.state.message = error.message || _t("Something went wrong. Please try again.");
        }
    }

    resetToIdle() {
        this.lookupSequence++;
        this.state.lastBarcode = "";
        this.state.manualBarcode = "";
        this.state.product = null;
        this.state.message = "";
        this.state.scannerReady = false;
        this.state.screen = "idle";
    }

    scanAnother() {
        this.lookupSequence++;
        this.state.lastBarcode = "";
        this.state.manualBarcode = "";
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
