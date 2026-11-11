#!/usr/bin/env python3
"""
Upstream Zero-PII & Secret Verification Gate.

Scans all git-tracked text files (`git ls-files`) for accidental leakage of:
1. Structural PII & secrets (local home directory paths, 21-digit Google Gaia IDs,
   19-digit ODLH database IDs, private LAN IPv4 addresses, Tailscale MagicDNS
   hostnames, non-example email addresses, Google API keys, OAuth tokens).
2. Blocked personal/residential tokens via salted SHA-256 1/2/3-gram digests so
   the scanner itself never embeds personal strings in tracked source code.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
HASH_SALT = "mylifebits-pii-v1:"

BINARY_SUFFIXES: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".db",
    ".sqlite",
    ".zip",
    ".gz",
}

STRUCTURAL_RULES: Sequence[Tuple[str, re.Pattern[str], Set[str]]] = (
    (
        "macos_user_home_path",
        re.compile(r"/Users/[A-Za-z0-9._-]+"),
        set(),
    ),
    (
        "linux_user_home_path",
        re.compile(r"/home/(?!runner\b|ubuntu\b|user\b)[A-Za-z0-9._-]+"),
        set(),
    ),
    (
        "windows_user_home_path",
        re.compile(r"C:\\Users\\[A-Za-z0-9._-]+"),
        set(),
    ),
    (
        "google_gaia_id",
        re.compile(r"\b1[01](?!0{19}\b)\d{19}\b"),
        {"uv.lock"},
    ),
    (
        "odlh_database_id",
        re.compile(r"\b1787\d{15}\b"),
        {"uv.lock"},
    ),
    (
        "private_lan_ipv4",
        re.compile(
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3}"
            r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        ),
        {"uv.lock"},
    ),
    (
        "tailscale_magicdns_host",
        re.compile(r"\b[A-Za-z0-9-]+\.tail[A-Za-z0-9-]+\.ts\.net\b"),
        set(),
    ),
    (
        "personal_email_address",
        re.compile(
            r"(?<![A-Za-z0-9/_.-])[A-Za-z0-9._%+-]+@"
            r"(?!example\.(?:com|org|net)\b|users\.noreply\.github\.com\b)"
            r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        {"uv.lock"},
    ),
    (
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        set(),
    ),
    (
        "oauth_access_token",
        re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
        set(),
    ),
)

# Opaque salted SHA-256 digests (`mylifebits-pii-v1:<normalized_token>`)
# guarding against regressions of personal names, residential street tokens,
# personal coordinates, birth/chronology dates, and hardware identifiers.
BLOCKED_TOKEN_SHA256: Set[str] = {
    "b725173b098e030187bc0c974fecc10d31eb4ebf642274d4d3440a2dc631d766",
    "e7f1190e09ea2a6f849e40025c1009217478982130e5ca497af5317e65d881c1",
    "3df995a0b7a31482272790e968a078f811ce99d3e0fd3620e54fa2f8ac8fd447",
    "090fd351862f13a55d3e75a1a8cb38bd375ca3b1d5f78428375c89a5adbca510",
    "f1255795b20397f04ae68c83b4e6b30c1fa17a81de42117a3a468c6b5d5d221f",
    "550af4102fbe16a0a57509462ae7f153af754ea85cee7f3789cff5b838d2a8cc",
    "b776e6cda5a5bb49d0f7c01cf93331cb24186ee90da2f9ef074d0234679a2c75",
    "9d548bd6077e546cb613ad96da76c5f587a8d0d9315cda4a7d705fa5d08cfb8a",
    "46c6f3d7eea1447b2281afa99de50d8304cd38de76d43476a0ec8d09fc226b62",
    "d2115b21d8f9cb305cbc3fcda412527cfe4387fd1e5f506cca2dc34a742a2173",
    "6b3156cc9a5831bc82ae0913bb95dcb0f5b76a966a8fbfaf7f4edecb376f1243",
    "341eb4e5afdf1d2bffb63416cf92e09f44621e8150547dbcf3f40ac793c098c4",
    "dab4e04822bdb89ac8c5972cd99fe026157b7dfec93c37fda15e28ecc408323b",
    "9d3748816ae6a0aeee62bb2fd9e0420c715dc97a2ee01d2de261cfc4cba6e7f9",
    "bb5d1cce441f23c89dd582e62261e79ee252f79d973ae668cc898383585fd10e",
    "373b85cbb305a2502957afb2097958dbd06a0ccf46126f20fb94d5b873425709",
    "f93a8bcd4a4ec86c210b8e3409b9ed0659d3e2c958f95929bcfd6108633ab9e2",
    "78d380deae9e08a43d6729a8b682cd4b24c0aa1d8b9d39a2e733882901c6eba4",
    "c34229c5eb689259579feffd14bb59fb8a0a9aaa6029ab30f8021338d688d1a1",
    "2cb2d2694759c5c5b5de47c2222aedab5e387dd6934fc121522a53fb6f1e6545",
    "d4b61393bcc0060add2f0ed768758d1a122f938df4f920d9de8f7af54a8a4a9f",
    "80ac4241a554eba87f8ba5bbf89e5a27f6eb043854906d6a30258d44898773b1",
    "16ebf73e102d73483577dc8b7cb85627b71a25e100172ee99a4c41f78ce61e3c",
    "f06de3314734501304f892918f5f25f02760714e1ecfe0ef7d7afe166cab72db",
    "02ba8e43b10ea5d1c719e9dd6e92e6f61faed53e6971641526d1540a904650cb",
    "21d2a593e09fa4bd074561dc1444340b94f5bf28efdf24465fc08f86aca2e11d",
    "f5b82c902d4497afec8ce6c88c93617018f4ae6b52127563104c06edb561a6e3",
    "d3b1ad0f62a48397895659caec6119174bb5f5e321b4464597a1dbabba9cdab4",
    "65ebbc3ad999a7e10ebeadb2925665e00ab7a47d36f06c55c371ae197948e686",
}

TOKEN_RE = re.compile(r"-?\d+\.\d+|[a-z0-9][a-z0-9._-]*")


def _digest_token(token: str) -> str:
    return hashlib.sha256((HASH_SALT + token).encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-1]}"


def list_tracked_files(repo_root: Path) -> List[Path]:
    res = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    paths: List[Path] = []
    for raw in res.stdout.splitlines():
        rel = raw.strip()
        if not rel:
            continue
        p = repo_root / rel
        if p.is_file():
            paths.append(p)
    return paths


def is_binary_file(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def scan_file(
    path: Path,
    repo_root: Path,
    blocked_hashes: Set[str],
) -> List[Dict[str, object]]:
    rel_path = path.relative_to(repo_root).as_posix()
    if is_binary_file(path):
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: List[Dict[str, object]] = []
    is_test_file = rel_path.startswith("tests/")

    for line_no, line in enumerate(text.splitlines(), start=1):
        # 1. Structural PII & secret regexes
        for rule_name, pattern, skip_files in STRUCTURAL_RULES:
            if rel_path in skip_files:
                continue
            if rule_name == "private_lan_ipv4" and is_test_file:
                continue
            for m in pattern.finditer(line):
                findings.append(
                    {
                        "file": rel_path,
                        "line": line_no,
                        "rule": rule_name,
                        "preview": _redact(m.group(0)),
                    }
                )

        # 2. Salted SHA-256 1/2/3-gram token digest checks
        if rel_path != "uv.lock":
            tokens = [t.strip("._-") or t for t in TOKEN_RE.findall(line.lower())]
            candidates: List[str] = []
            n = len(tokens)
            for i in range(n):
                candidates.append(tokens[i])
                # Also check raw token with punctuation (e.g. zip filenames or dates)
                if i + 1 < n:
                    candidates.append(f"{tokens[i]} {tokens[i + 1]}")
                if i + 2 < n:
                    candidates.append(f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}")
            # Include raw whitespace/quote-delimited chunks for exact filenames
            for raw_tok in re.findall(r"[a-z0-9_-]+\.[a-z0-9._-]+", line.lower()):
                candidates.append(raw_tok)

            for cand in candidates:
                if _digest_token(cand) in blocked_hashes:
                    findings.append(
                        {
                            "file": rel_path,
                            "line": line_no,
                            "rule": "blocked_pii_token_digest",
                            "preview": _redact(cand),
                        }
                    )
                    break

    return findings


def run_audit(paths: Iterable[Path], repo_root: Path) -> List[Dict[str, object]]:
    blocked = set(BLOCKED_TOKEN_SHA256)
    extra = os.environ.get("PII_EXTRA_BLOCKLIST", "").strip()
    if extra:
        for item in extra.split(","):
            norm = item.strip().lower()
            if norm:
                blocked.add(_digest_token(norm))

    all_findings: List[Dict[str, object]] = []
    for p in paths:
        all_findings.extend(scan_file(p, repo_root, blocked))
    return all_findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit git-tracked files for PII and secrets.")
    parser.add_argument("files", nargs="*", help="Optional subset of files to scan.")
    args = parser.parse_args(argv)

    if args.files:
        targets = [Path(f).resolve() for f in args.files if Path(f).is_file()]
    else:
        targets = list_tracked_files(WORKSPACE_DIR)

    findings = run_audit(targets, WORKSPACE_DIR)
    print("=================================================================")
    print("  UPSTREAM ZERO-PII & SECRET AUDIT GATE")
    print("=================================================================")
    print(f"  Scanned tracked files : {len(targets)}")
    print(f"  Violations detected   : {len(findings)}")

    if findings:
        print("\n[FAIL] PII or environment-specific leakage detected:")
        for f in findings[:50]:
            print(f"  - {f['file']}:{f['line']} [{f['rule']}] ({f['preview']})")
        if len(findings) > 50:
            print(f"  ... and {len(findings) - 50} additional findings.")
        return 1

    print("[PASS] Zero PII, personal paths, or secrets detected across tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
