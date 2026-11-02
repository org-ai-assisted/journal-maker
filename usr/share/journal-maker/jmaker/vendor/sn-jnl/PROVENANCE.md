# Vendored: Springer Nature `sn-jnl` LaTeX class

Springer Nature distributes `sn-jnl.cls` only via its own site / Overleaf (no CTAN
package, so not in texlive-publishers like elsarticle / IEEEtran / acmart). It is
vendored here so the venue `.tex` compile-verify (sandbox) can build the Springer
submission source. Byte-exact copies; `.gitattributes` pins `-text` so no EOL
normalization shifts the sha.

## Source

- Package: Springer Nature journal article LaTeX template, December 2024 version.
- URL: https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/18782940/data/v12
- Landing page: https://www.springernature.com/gp/authors/campaigns/latex-author-support
- Retrieved: 2026-11-02.
- Package zip sha256: 812e76dcaa9c28dc1bff1fb6065d51729b67d4ea140552a05088317414a3ecae

## Files + sha256 (the drift-guard pin; see tests/test_vendor_snjnl.py)

- sn-jnl.cls          36d0c3273a59d48dc6a9c7b080dfa1ec50dc10229d8751568d1f2e490ffa5ecc
- sn-mathphys-num.bst b3a7c7fbcc1e7f9619de634fcea2f5bb7a245818a5942bc576e40ea001633332

Only these two are vendored: the class, and the numeric bibliography style matching
the site's IEEE-numbered references. The package's other `.bst` styles are not used.

## License

- LPPL 1.3c-or-later, maintenance status "maintained" (stated in each file header) --
  permits redistribution and modification. This is the license texlive/CTAN
  redistribute LaTeX classes under.
- The files carry the standard docstrip header line "This file may only be
  distributed together with a copy of the LaTeX base system." That is generic
  docstrip boilerplate present on LPPL files redistributed throughout texlive/CTAN;
  the operative grant is LPPL 1.3c. Recorded here for honesty, not as a bar to the
  vendoring (which only reaches an environment where the LaTeX base system is present).

## Refresh

Springer bumps this package in place (the `\ProvidesClass` stamp stays `v0.1
2019/11/18` even in the Dec-2024 release, so the sha + package date are the real
version). To update: re-fetch the URL, re-verify the LPPL header, replace both files
byte-exact, and update the pinned sha256 in PROVENANCE.md AND tests/test_vendor_snjnl.py
in the same commit (a human reviews the new upstream).
