#!/usr/bin/python3 -Bsu
"""Drift guard for the vendored Springer Nature `sn-jnl` class.

sn-jnl is not in texlive (unlike elsarticle / IEEEtran / acmart), so it is vendored
byte-exact under jmaker/vendor/sn-jnl/. These pins FAIL the build the moment a
vendored copy diverges from the upstream version we vetted -- an accidental edit, an
EOL normalization, or an unreviewed refresh. Updating the pin is a deliberate,
reviewed edit alongside PROVENANCE.md (see that file's Refresh section)."""
import hashlib
import os
import unittest

from jmaker import generate as g

VENDOR = os.path.join(os.path.dirname(os.path.abspath(g.__file__)), "vendor", "sn-jnl")

# Pinned sha256 of the December 2024 Springer package (see PROVENANCE.md).
PINS = {
    "sn-jnl.cls": "36d0c3273a59d48dc6a9c7b080dfa1ec50dc10229d8751568d1f2e490ffa5ecc",
    "sn-mathphys-num.bst": "b3a7c7fbcc1e7f9619de634fcea2f5bb7a245818a5942bc576e40ea001633332",
}


class TestVendoredSnjnl(unittest.TestCase):
    def test_sha256_matches_pin(self):
        for name, want in PINS.items():
            path = os.path.join(VENDOR, name)
            with open(path, "rb") as fh:
                got = hashlib.sha256(fh.read()).hexdigest()
            self.assertEqual(got, want, "%s drifted from the vetted upstream; if this "
                             "is a deliberate refresh, update PROVENANCE.md + this pin "
                             "together" % name)

    def test_lppl_header_present(self):
        # A refresh that dropped the license would still match no pin, but guard the
        # grant explicitly: the class must keep its LPPL statement.
        with open(os.path.join(VENDOR, "sn-jnl.cls"), "rb") as fh:
            head = fh.read(4096).decode("latin-1")
        self.assertIn("LaTeX Project Public License", head)


if __name__ == "__main__":
    unittest.main()
