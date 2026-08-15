/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { loadJS } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { delay } from "@web/core/utils/concurrency";

// The `@web/webclient/barcode/*` modules are part of the backend/webclient
// asset bundles and are therefore not available on public website pages.
// The few helpers used below are reimplemented here so the price checker
// stays self-contained on the frontend.

function isVideoElementReady(video) {
    return video.readyState >= 2; // HAVE_CURRENT_DATA
}

function isBarcodeScannerSupported() {
    return !!(browser.navigator.mediaDevices && browser.navigator.mediaDevices.getUserMedia);
}

/**
 * BarcodeDetector-like polyfill built on the ZXing library (loaded lazily).
 * Mirrors the API of Odoo's `@web/webclient/barcode/ZXingBarcodeDetector`.
 *
 * @param {ZXing} ZXing the ZXing library
 * @returns {class} ZXingBarcodeDetector class
 */
function buildZXingBarcodeDetector(ZXing) {
    const ZXingFormats = new Map([
        ["aztec", ZXing.BarcodeFormat.AZTEC],
        ["code_39", ZXing.BarcodeFormat.CODE_39],
        ["code_128", ZXing.BarcodeFormat.CODE_128],
        ["data_matrix", ZXing.BarcodeFormat.DATA_MATRIX],
        ["ean_8", ZXing.BarcodeFormat.EAN_8],
        ["ean_13", ZXing.BarcodeFormat.EAN_13],
        ["itf", ZXing.BarcodeFormat.ITF],
        ["pdf417", ZXing.BarcodeFormat.PDF_417],
        ["qr_code", ZXing.BarcodeFormat.QR_CODE],
        ["upc_a", ZXing.BarcodeFormat.UPC_A],
        ["upc_e", ZXing.BarcodeFormat.UPC_E],
    ]);
    const allSupportedFormats = Array.from(ZXingFormats.keys());

    class ZXingBarcodeDetector {
        constructor(opts = {}) {
            const formats = opts.formats || allSupportedFormats;
            const hints = new Map([
                [
                    ZXing.DecodeHintType.POSSIBLE_FORMATS,
                    formats.map((format) => ZXingFormats.get(format)),
                ],
                [ZXing.DecodeHintType.TRY_HARDER, true],
            ]);
            this.reader = new ZXing.MultiFormatReader();
            this.reader.setHints(hints);
        }

        async detect(video) {
            if (!isVideoElementReady(video)) {
                throw new DOMException("HTMLVideoElement is not ready", "InvalidStateError");
            }
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const luminanceSource = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
            const binaryBitmap = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(luminanceSource));
            try {
                const result = this.reader.decode(binaryBitmap);
                return [{ rawValue: result.getText() }];
            } catch (err) {
                if (err.name === "NotFoundException") {
                    return [];
                }
                throw err;
            }
        }
    }

    ZXingBarcodeDetector.getSupportedFormats = async () => allSupportedFormats;
    return ZXingBarcodeDetector;
}

/**
 * Inline camera barcode scanner.
 *
 * Odoo 17 has no inline camera scanner component (its own `BarcodeScanner`
 * opens a dialog), so this is an inline port of the core detection loop used
 * by `web.BarcodeDialog`, rendered directly inside the price-checker page.
 */
export class BarcodeScanner extends Component {
    static template = "pos_kisok_price_checker.BarcodeScanner";
    static props = {
        facingMode: { type: String, optional: true },
        delayBetweenScan: { type: Number, optional: true },
        onReady: { type: Function, optional: true },
        onResult: { type: Function },
        onError: { type: Function, optional: true },
    };
    static defaultProps = {
        facingMode: "environment",
        delayBetweenScan: 1200,
        onReady: () => {},
        onError: () => {},
    };

    setup() {
        this.videoRef = useRef("video");
        this.stream = null;
        this.detector = null;
        this.state = useState({ isReady: false });
        this.lastScanAt = 0;
        this.scanTimer = null;

        onWillStart(async () => {
            let DetectorClass;
            // Use the Barcode Detection API if available (mainly Chrome on
            // Android) and fall back to the ZXing library otherwise.
            if ("BarcodeDetector" in window) {
                DetectorClass = window.BarcodeDetector;
            } else {
                await loadJS("/web/static/lib/zxing-library/zxing-library.js");
                DetectorClass = buildZXingBarcodeDetector(window.ZXing);
            }
            const formats = await DetectorClass.getSupportedFormats();
            this.detector = new DetectorClass({ formats });
        });

        onMounted(async () => {
            try {
                this.stream = await browser.navigator.mediaDevices.getUserMedia({
                    video: { facingMode: this.props.facingMode },
                    audio: false,
                });
            } catch (err) {
                this.onError(this._cameraError(err));
                return;
            }
            this.videoRef.el.srcObject = this.stream;
            await this.isVideoReady();
            this.scanTimer = setInterval(() => this.detectCode(), 100);
            this.props.onReady();
        });

        onWillUnmount(() => {
            clearInterval(this.scanTimer);
            this.scanTimer = null;
            if (this.stream) {
                this.stream.getTracks().forEach((track) => track.stop());
                this.stream = null;
            }
        });
    }

    /**
     * Check for camera preview element readiness.
     *
     * @returns {Promise} resolves when the video element is ready
     */
    async isVideoReady() {
        while (!isVideoElementReady(this.videoRef.el)) {
            await delay(10);
        }
        this.state.isReady = true;
    }

    _cameraError(err) {
        const messages = {
            NotFoundError: _t("No camera could be found on this device."),
            NotAllowedError: _t("Camera access was denied. Please allow it and try again."),
        };
        return new Error(
            messages[err.name] || (err && err.message) || _t("Could not start the camera.")
        );
    }

    onError(error) {
        if (this.props.onError) {
            this.props.onError(error);
        }
    }

    /**
     * Attempt to detect codes in the current camera preview's frame.
     */
    async detectCode() {
        if (!this.detector || !this.state.isReady) {
            return;
        }
        try {
            const codes = await this.detector.detect(this.videoRef.el);
            for (const code of codes) {
                // Ignore re-detections within the configured delay to avoid
                // spamming the server while a result is shown.
                const now = Date.now();
                if (now - this.lastScanAt < this.props.delayBetweenScan) {
                    continue;
                }
                this.lastScanAt = now;
                this.props.onResult(code.rawValue);
                break;
            }
        } catch (err) {
            this.onError(err);
        }
    }
}

/**
 * Public price checker used on /price-check/<slug> pages.
 *
 * Scans product barcodes with the phone camera (BarcodeDetector API or ZXing
 * fallback), queries the store-specific price and displays the result.
 */
export class PriceChecker extends Component {
    static template = "pos_kisok_price_checker.PriceChecker";
    static components = { BarcodeScanner };
    static props = {
        slug: { type: String },
        taxIncluded: { type: Boolean, optional: true },
    };
    static defaultProps = {
        taxIncluded: true,
    };

    setup() {
        this.rpc = useService("rpc");
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
            const result = await this.rpc("/price-check/lookup", {
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
