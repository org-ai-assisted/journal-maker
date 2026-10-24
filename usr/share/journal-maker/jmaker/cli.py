#!/usr/bin/python3 -Bsu
"""journal-maker command-line entry point.

Subcommands:
  build    articles/ + journal.toml -> static site (HTML + PDF + meta + sitemap)
  check    gate a built site: Scholar compliance + PDF sanity + PDF security
  vtscan   VirusTotal every built asset before publishing (checklist + results)
  dewiki   MediaWiki source -> Markdown drafting starting point
  selftest run the unit tests
  version  print version
"""

import argparse
import os
import sys
import unittest

import jmaker
from jmaker import check as checker
from jmaker import generate


def _cmd_build(args):
    try:
        count, out = generate.build(args.articles, args.journal, args.out,
                                    skip_pdf=args.skip_pdf)
    except generate.BuildError as exc:
        print("build error: %s" % exc, file=sys.stderr)
        return 1
    print("built %d article(s) into %s" % (count, out))
    return 0


def _cmd_check(args):
    return checker.main([args.site])


def _cmd_vtscan(args):
    from jmaker import vtscan
    return vtscan.main(args.site, client=args.client, out=args.out,
                       upload=not args.no_upload)


def _cmd_dewiki(args):
    from jmaker import dewiki
    md = dewiki.convert_file(args.source)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print("wrote %s" % args.out)
    else:
        sys.stdout.write(md)
    return 0


def _cmd_selftest(args):
    here = os.path.dirname(os.path.abspath(__file__))
    top = os.path.dirname(here)
    suite = unittest.defaultTestLoader.discover(
        os.path.join(here, "tests"), top_level_dir=top)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _cmd_version(args):
    print("journal-maker %s" % jmaker.__version__)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="journal-maker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pbuild = sub.add_parser("build", help="build the static site")
    pbuild.add_argument("--articles", default="articles")
    pbuild.add_argument("--journal", default="journal.toml")
    pbuild.add_argument("--out", default="_site")
    pbuild.add_argument("--skip-pdf", action="store_true",
                        help="skip PDF generation (fast HTML-only iteration)")
    pbuild.set_defaults(func=_cmd_build)

    pcheck = sub.add_parser("check", help="gate a built site")
    pcheck.add_argument("site")
    pcheck.set_defaults(func=_cmd_check)

    pvt = sub.add_parser("vtscan", help="VirusTotal all built assets")
    pvt.add_argument("site")
    pvt.add_argument("--client", default="vtai.py",
                     help="VirusTotal client command (default: vtai.py)")
    pvt.add_argument("--out", default=None,
                     help="results JSON path (default: <site>/vt-results.json)")
    pvt.add_argument("--no-upload", action="store_true",
                     help="hash-lookup only; never upload")
    pvt.set_defaults(func=_cmd_vtscan)

    pde = sub.add_parser("dewiki", help="MediaWiki source -> Markdown draft")
    pde.add_argument("source")
    pde.add_argument("-o", "--out", default=None)
    pde.set_defaults(func=_cmd_dewiki)

    pself = sub.add_parser("selftest", help="run unit tests")
    pself.set_defaults(func=_cmd_selftest)

    pver = sub.add_parser("version", help="print version")
    pver.set_defaults(func=_cmd_version)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
