#!/usr/bin/env python3
"""Build example-source-data/my-flashcards.js from my_cards.csv, then publish.

tsofa.html loads its cards from that .js file (see the <script src> tag near the
top of tsofa.html), so this script only rewrites the data file - tsofa.html
itself is never modified.

    my_cards.csv  ->  example-source-data/my-flashcards.js  ->  git commit/push

Usage
    python update_and_publish.py                  rebuild the deck + publish
    python update_and_publish.py --dry-run        show what would change
    python update_and_publish.py --no-push        rebuild + commit, no push
    python update_and_publish.py --no-git         only rebuild the file
    python update_and_publish.py --topic "JLPT N4"      override the topic
    python update_and_publish.py --justification left   left / right / center
    python update_and_publish.py --skip-header    CSV's first row is a header
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "my_cards.csv")
DECK_PATH = os.path.join(HERE, "example-source-data", "my-flashcards.js")
INDEX_PATH = os.path.join(HERE, "tsofa.html")
DECK_REF = "example-source-data/my-flashcards.js"
DEFAULT_TOPIC = "My Custom Deck"
DEFAULT_JUSTIFICATION = "center"
VALUE_RE = {
    "TOPIC": re.compile(r"^\s*(?:let|const|var)\s+TOPIC\s*=\s*(.+?);\s*$", re.M),
    "JUSTIFICATION": re.compile(r"^\s*(?:let|const|var)\s+JUSTIFICATION\s*=\s*(.+?);\s*$", re.M),
}


def escape_template_literal(text):
    """Escape a card for a JS template literal: backslash first, then ` and ${."""
    return (text.replace("\\", "\\\\")
                .replace("`", "\\`")
                .replace("${", "\\${"))


def read_cards(path, skip_header):
    cards = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if skip_header and i == 0:
                continue
            if not row or len(row) < 2:
                continue
            question, answer = row[0].strip(), row[1].strip()
            if not question and not answer:
                continue
            cards.append((question, answer))
    return cards


def existing_value(key, fallback):
    """Keep whatever the deck file already uses, so rebuilding does not reset it."""
    if not os.path.isfile(DECK_PATH):
        return fallback
    with open(DECK_PATH, "r", encoding="utf-8-sig", newline="") as fh:
        match = VALUE_RE[key].search(fh.read())
    if not match:
        return fallback
    raw = match.group(1).strip()
    try:
        return json.loads(raw)          # deck stores plain double-quoted strings
    except ValueError:
        return raw.strip("\"'")


def build_deck(cards, topic, justification):
    lines = ["let TOPIC = %s;" % json.dumps(topic, ensure_ascii=False),
             "let JUSTIFICATION = %s;" % json.dumps(justification, ensure_ascii=False),
             "let FLASHCARDS = ["]
    last = len(cards) - 1
    for i, (question, answer) in enumerate(cards):
        lines.append("[`%s`, `%s`]%s" % (escape_template_literal(question),
                                         escape_template_literal(answer),
                                         "," if i < last else ""))
    lines.append("];")
    return "\r\n".join(lines) + "\r\n"
def find_git():
    if shutil.which("git"):
        return "git"
    gh = os.path.join(os.environ.get("LOCALAPPDATA", ""), "GitHubDesktop")
    if os.path.isdir(gh):
        for folder in sorted(os.listdir(gh), reverse=True):
            if folder.startswith("app-"):
                candidate = os.path.join(gh, folder, "resources", "app", "git", "cmd", "git.exe")
                if os.path.isfile(candidate):
                    return candidate
    return None


def git_run(git, args):
    print("   $ git %s" % " ".join(args))
    try:
        return subprocess.run([git] + args, cwd=HERE, capture_output=True, text=True)
    except Exception as exc:
        print("   ! %s" % exc)
        return None


def publish(message, push):
    print("Step 2: publishing with git")
    git = find_git()
    if not git:
        print("  git not found - commit and push manually")
        return 1

    status = git_run(git, ["status", "--short"])
    if status and status.stdout.strip():
        print("  changes to stage:")
        for line in status.stdout.strip().splitlines()[:20]:
            print("     " + line)

    git_run(git, ["add", "-A"])
    commit = git_run(git, ["commit", "-m", message])
    text = ((commit.stdout or "") + (commit.stderr or "")).strip() if commit else ""
    if text:
        print("  " + text.splitlines()[0])
    if "nothing to commit" in text or "nothing added" in text:
        print("  nothing to commit - the repo is already up to date")
        return 0

    if not push:
        print("  push skipped (--no-push)")
        return 0
    result = git_run(git, ["push", "origin", "main"])
    if result is None or result.returncode != 0:
        result = git_run(git, ["push"])
    ok = bool(result and result.returncode == 0)
    if not ok and result is not None:
        print("  " + (result.stderr or result.stdout).strip().splitlines()[-1][:120])
    print("  %s" % ("pushed" if ok else "push failed - run 'git push' manually"))
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rebuild %s from %s (tsofa.html is not touched)."
                    % (os.path.relpath(DECK_PATH, HERE), os.path.basename(CSV_PATH)))
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    parser.add_argument("--no-git", action="store_true", help="only rebuild the deck file")
    parser.add_argument("--no-push", action="store_true", help="commit locally, do not push")
    parser.add_argument("--topic", help="deck title (default: keep the current one)")
    parser.add_argument("--justification", choices=["left", "right", "center"])
    parser.add_argument("--skip-header", action="store_true", help="ignore the first CSV row")
    parser.add_argument("--message", default="Update flashcards from my_cards.csv")
    args = parser.parse_args(argv)

    print("Step 1: %s -> %s" % (os.path.basename(CSV_PATH),
                                os.path.relpath(DECK_PATH, HERE)))
    if not os.path.isfile(CSV_PATH):
        print("  ERROR: %s not found" % CSV_PATH)
        return 1

    cards = read_cards(CSV_PATH, args.skip_header)
    if not cards:
        print("  ERROR: no cards found - the CSV needs two columns (question,answer)")
        return 1

    topic = args.topic or existing_value("TOPIC", DEFAULT_TOPIC)
    justification = args.justification or existing_value("JUSTIFICATION", DEFAULT_JUSTIFICATION)
    deck = build_deck(cards, topic, justification)

    current = None
    if os.path.isfile(DECK_PATH):
        with open(DECK_PATH, "r", encoding="utf-8-sig", newline="") as fh:
            current = fh.read()

    print("  cards         : %d" % len(cards))
    print("  TOPIC         : %s" % topic)
    print("  JUSTIFICATION : %s" % justification)

    if current == deck:
        print("  deck file     : already up to date, nothing to write")
        return 0
    if args.dry_run:
        print("  deck file     : would be rewritten (--dry-run, wrote nothing)")
        return 0

    with open(DECK_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(deck)
    print("  deck file     : rewritten (%d bytes, CRLF, UTF-8 no BOM)" % len(deck))

    if os.path.isfile(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8", errors="replace") as fh:
            if DECK_REF not in fh.read():
                print("  WARNING: %s does not reference %s"
                      % (os.path.basename(INDEX_PATH), DECK_REF))

    if args.no_git:
        print("Step 2: skipped (--no-git)")
        return 0
    return publish(args.message, not args.no_push)


if __name__ == "__main__":
    sys.exit(main())
