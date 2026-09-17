# Vendored barcode decoder

`zxing-browser-0.2.1.min.js` is the unmodified self-contained UMD bundle from the official npm package `@zxing/browser@0.2.1`, downloaded 2026-09-17. No npm install/build or runtime CDN is required. This bundle contains the ZXing decoder and ts-custom-error helper; the complete bundle bytes are pinned, not resolved dynamically.

Source tarball: https://registry.npmjs.org/@zxing/browser/-/browser-0.2.1.tgz

Registry integrity (verified before extraction):

```text
sha512-92pVfVDUXbc15xu9vIEmhNyqIEASMEkDF92CwT6T+7sg2EHXJRktH9CQKoQSXe51UtbNsj+Fm09H/JBWHMs/Sw==
```

Delivered JavaScript SHA-256:

```text
066bc34edfcdd4a33f0964aeec967752a0dea1ccaf36e58e319ac9fcb5070f6a
```

Licenses retained alongside the bundle:

- `ZXING-BROWSER-LICENSE.txt`: MIT, from the same browser package.
- `ZXING-LIBRARY-LICENSE.txt`: Apache-2.0, from the official `@zxing/library@0.23.0` package. The prebuilt browser bundle does not separately declare its bundled core version; no exact-core-version claim is made.
- `TS-CUSTOM-ERROR-LICENSE.txt`: MIT, from official `ts-custom-error@3.3.1`. This helper appears in the upstream bundle source map.

Upstream project: https://github.com/zxing-js/browser ; decoder: https://github.com/zxing-js/library ; helper: https://github.com/adriengibrat/ts-custom-error . Original license comments in the minified distribution are retained. A source-map reference may cause browser developer tools to request a missing local map; no external fetch is configured.

The application calls only the camera/canvas decoding API with local video, never image-URL helpers. Formats are explicitly restricted in `../barcode-scan.js`. Keep numeric enum hints synchronized with the bundle when upgrading; test leading-zero EAN-13 using `node --test tests/barcode_browser.cjs`.
