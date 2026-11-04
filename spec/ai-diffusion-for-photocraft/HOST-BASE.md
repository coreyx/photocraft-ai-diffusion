# Host base

The PhotoCraft fork that carries the process plug-in host (Part A of [requirements.md](requirements.md)).

| | |
|---|---|
| Fork | [`coreyx/photocraft`](https://github.com/coreyx/photocraft), a GitHub fork of [`storytold/photocraft`](https://github.com/storytold/photocraft) |
| Branch | `feat/process-plugins` |
| Base commit | `8e82c0e728ee03eb0ce7e5d12289f98bae1595c9` (upstream `main`, 2026-11-04) |
| Remotes | `origin` = the fork, `upstream` = `storytold/photocraft` |
| Toolchain used | Rust 1.99.1 (MSVC, Windows 11 x64), `cargo-nextest` 0.9.151, target `wasm32-unknown-unknown` |

## Baseline gate

`cargo xtask ci` on the untouched base commit, before any change, run on the development machine (Windows 11 x64, 32 logical cores).

**Run with fonts.** PhotoCraft's tests need the optional font checkout. Without it, 58 tests fail with "No glyph for …" panics. Clone [`storytold/craft-fonts`](https://github.com/storytold/craft-fonts) beside the fork, then set `CRAFT_FONTS_DIR` to its absolute path before every gate run, as `docs/development.md` › Fonts describes.

| Step | Result on the base |
|---|---|
| fmt, clippy, layers, scorecard | ok |
| test (nextest, `ci` profile) | **4 tests fail**; everything else passes |
| panic_hunt | ok (1 passed) |
| doctest | ok |
| wasm | ok (24 crates, plus `photocraft-codecs --features heif`) |
| i18n | report only (ok) |

**Failures that already exist on the base** (they reproduce when run alone, so they aren't flaky; all depend on this machine's memory or GPU, not on our code):

| Test | Failure |
|---|---|
| `photocraft-engine::it atn_crystallize_cell_size::fractional_cell_sizes_remain_native_and_are_refused_by_strict_export` | "not enough working memory for this operation" (memory admission) |
| `photocraft-engine::it atn_crystallize_cell_size::integer_cell_sizes_and_defaults_preserve_playback` | Same memory-admission error |
| `photocraft-algo tests::relight_admission_tracks_the_document_dependent_working_set` | Working-set assertion (`crates/algo/src/tests.rs:16`) |
| `photocraft-gpu::it timing::a_refresh_that_submits_several_times_is_one_measurement` | GPU timing: summed GPU time below the measured wait |

**How host tasks are gated.** `cargo xtask ci` stops at the first failing step, so on this machine it always stops at `test` because of the four tests above. A host task's gate passes when:
1. `cargo xtask ci` reports fmt, clippy, layers and scorecard as ok;
2. the only failing tests are the four listed above;
3. the steps that `ci` then skips pass when run on their own:
   - `cargo nextest run --profile ci --workspace --locked --features heif --lib --bins --tests --run-ignored only -E 'binary_id(photocraft-engine::panic_hunt)'`
   - `cargo test --workspace --locked --features heif --doc`
   - `cargo xtask wasm`
   - `cargo xtask i18n-coverage`

The fork leaves PhotoCraft's own CI workflows unchanged, and they run on GitHub's hosted runners. There, the four machine-dependent tests are expected to pass as they do upstream.
