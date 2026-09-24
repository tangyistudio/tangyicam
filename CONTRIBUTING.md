# Contributing

Use a new branch and submit a focused pull request. Keep camera transport local by default, preserve third-party notices, and include a reproducible test for behavior changes. Do not commit user scenes, private keys, API credentials, model weights or generated film assets.

Run the security tests and deterministic build in README.md. Blender tests use an isolated profile. Update compatibility claims only with actual version and device evidence; keep hardware-pending items explicit.

For demo or documentation changes, also run `node --test test/demo-camera.test.mjs`, `python tools/check_docs.py`, and `node tools/qa-demo.mjs`. Keep the browser demo explicitly separate from real Blender/device validation. See [QA scope](docs/QA.md).

For demo translations, edit `site/index.template.html` and `site/locales/*.json`, then run `python tools/build_demo.py`. Do not hand-edit generated HTML or `docs/demo/messages.mjs`; `python tools/build_demo.py --check` must pass.
