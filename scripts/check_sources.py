#!/usr/bin/env python3
"""Compare live Social Welfare Department hub pages with the committed source manifest.

Run monthly (or before refreshing data). This script only reports drift.
Scheduling the run is left to whoever operates the site.

    python3 scripts/check_sources.py
    python3 scripts/check_sources.py --write-manifest
    python3 -m unittest discover -s scripts -p 'test_*.py'

Exit 0 when hub download links still match scripts/source-manifest.json and the
per-URL HEAD metadata (Last-Modified, ETag, Content-Length) still matches too.
Exit 1 on link drift, metadata drift, or a fetch error that blocks comparison.

The manifest stores links plus a files map:

    {
      "hubs": {"csse": "https://..."},
      "links": {"csse": ["https://.../file.pdf"]},
      "files": {
        "https://.../file.pdf": {
          "lastModified": "Wed, 15 Oct 2025 02:07:47 GMT",
          "etag": null,
          "contentLength": 310675
        }
      }
    }

Missing headers are stored as null. A response with no usable headers is a
warning, not a failure, unless that URL previously had usable headers.
File bodies are never downloaded: HEAD is preferred, and a failed HEAD falls
back to GET with the socket closed after the headers.
"""

from __future__ import annotations

import http.client
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "source-manifest.json"
SWD = "https://www.swd.gov.hk"
UA = "find-service/0.1 (Find Service source check; public pages only)"

HUBS = {
    "csse": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/index.html",
    "ccse": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_ccse/",
    "mss": f"{SWD}/tc/pubsvc/medical/cat_medical/medicalsoc/",
    "ifsc": f"{SWD}/tc/pubsvc/family/cat_family/ifs/ifscbydistrict/index.html",
}

METADATA_FIELDS = ("lastModified", "etag", "contentLength")
HEADER_WORKERS = 3
HEADER_INTERVAL_SECONDS = 0.2
HEADER_TIMEOUT_SECONDS = 20
# Statuses that mean "do not fail the nightly check".
QUIET_STATUSES = {"match", "skip", "gained_headers"}


class FetchError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(reason)


class RequestGate:
    """Space out request starts so parallel workers do not burst."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay < 0:
                delay = 0.0
            self._next = max(self._next, now) + self.interval
        if delay:
            time.sleep(delay)


class _CallGate:
    """Per-URL gate that shares pacing but remembers a HEAD→GET fallback."""

    def __init__(self, parent: RequestGate) -> None:
        self.parent = parent
        self.fell_back = False

    def wait(self) -> None:
        self.parent.wait()


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="ignore")


def links_from(html: str) -> list[str]:
    found = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        lower = href.lower()
        if not any(lower.endswith(suffix) for suffix in (".pdf", ".xls", ".xlsx", ".doc", ".docx")):
            continue
        absolute = href if href.startswith("http") else SWD + href
        if absolute not in found:
            found.append(absolute)
    return found


def link_changes(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    old_set = set(old)
    new_set = set(new)
    return sorted(new_set - old_set), sorted(old_set - new_set)


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_content_length(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text or not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def metadata_from_headers(headers) -> dict:
    """Copy Last-Modified, ETag, and Content-Length. Missing headers become null."""
    if headers is None:
        found = {}
    else:
        found = {}
        for key, value in headers.items():
            found[str(key).lower()] = value
    return {
        "lastModified": _blank_to_none(found.get("last-modified")),
        "etag": _blank_to_none(found.get("etag")),
        "contentLength": parse_content_length(found.get("content-length")),
    }


def clean_metadata(meta: dict | None) -> dict:
    meta = meta or {}
    return {
        "lastModified": _blank_to_none(meta.get("lastModified")),
        "etag": _blank_to_none(meta.get("etag")),
        "contentLength": parse_content_length(meta.get("contentLength")),
    }


def usable_metadata(meta: dict | None) -> bool:
    cleaned = clean_metadata(meta)
    return any(cleaned[key] is not None for key in METADATA_FIELDS)


def _last_modified_key(value: object):
    text = _blank_to_none(value)
    if text is None:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ("raw", text)
    if parsed is None:
        return ("raw", text)
    return ("ts", int(parsed.timestamp()))


def _compare_key(field: str, value: object):
    if field == "lastModified":
        return _last_modified_key(value)
    if field == "contentLength":
        return parse_content_length(value)
    return _blank_to_none(value)


def classify_metadata(saved: dict | None, live: dict | None) -> dict:
    """Compare stored HEAD metadata with a fresh read.

    Returns status:
      match           overlapping headers agree
      changed         at least one overlapping header differs
      headers_gone    stored headers were usable and the new response has none
      skip            nothing usable on either side, or no overlapping field
      gained_headers  nothing was stored, and the server now sends headers
      no_baseline     this URL has no metadata object in the manifest
    """
    if saved is None or not isinstance(saved, dict):
        return {"status": "no_baseline", "changes": [], "reason": "no_baseline"}

    old = clean_metadata(saved)
    new = clean_metadata(live)
    old_ok = usable_metadata(old)
    new_ok = usable_metadata(new)
    if not new_ok:
        status = "headers_gone" if old_ok else "skip"
        return {"status": status, "changes": [], "reason": status}
    if not old_ok:
        return {"status": "gained_headers", "changes": [], "reason": "gained_headers"}

    changes = []
    comparable = False
    for field in METADATA_FIELDS:
        old_key = _compare_key(field, old[field])
        new_key = _compare_key(field, new[field])
        if old_key is None or new_key is None:
            # A single missing header is not drift. SWD omits ETag entirely.
            continue
        comparable = True
        if old_key != new_key:
            changes.append({"field": field, "old": old[field], "new": new[field]})
    if not comparable:
        return {"status": "skip", "changes": [], "reason": "no_overlap"}
    if changes:
        return {"status": "changed", "changes": changes, "reason": "changed"}
    return {"status": "match", "changes": [], "reason": "match"}


def status_is_failure(status: str) -> bool:
    return status not in QUIET_STATUSES


def format_metadata(meta: dict | None) -> str:
    cleaned = clean_metadata(meta)
    parts = []
    for field in METADATA_FIELDS:
        value = cleaned[field]
        shown = "null" if value is None else value
        parts.append(f"{field}={shown}")
    return "；".join(parts)


def _request_once(url: str, method: str, timeout: float) -> tuple[int, dict, str | None]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(url, "網址不是 http(s)")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    connection_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = connection_cls(parts.hostname, parts.port, timeout=timeout)
    try:
        conn.request(
            method,
            path,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        # Copy headers, then close without reading a body.
        header_map = {str(key): value for key, value in response.headers.items()}
        location = response.headers.get("Location")
        status = response.status
        return status, header_map, location
    except FetchError:
        raise
    except (http.client.HTTPException, OSError, TimeoutError) as exc:
        raise FetchError(url, f"{method} {exc}") from exc
    finally:
        conn.close()


def _exchange(url: str, method: str, timeout: float, gate: RequestGate | _CallGate | None = None) -> tuple[int, dict]:
    current = url
    current_method = method
    for _ in range(6):
        if gate is not None:
            gate.wait()
        status, headers, location = _request_once(current, current_method, timeout)
        if status in (301, 302, 303, 307, 308) and location:
            current = urllib.parse.urljoin(current, location.strip())
            if status == 303:
                current_method = "GET"
            continue
        return status, headers
    raise FetchError(url, "重新導向次數過多")


def fetch_header_metadata(url: str, timeout: float = HEADER_TIMEOUT_SECONDS, gate: RequestGate | _CallGate | None = None) -> dict:
    """Read Last-Modified / ETag / Content-Length. HEAD first; GET headers only if HEAD fails."""
    head_error: FetchError | None = None
    try:
        status, headers = _exchange(url, "HEAD", timeout, gate)
    except FetchError as exc:
        head_error = exc
    else:
        if status in (404, 410):
            # The file is gone. A second GET would only repeat the same answer.
            raise FetchError(url, f"HTTP {status}")
        if 200 <= status < 300:
            meta = metadata_from_headers(headers)
            if usable_metadata(meta):
                return meta
            head_error = FetchError(url, "HEAD 沒有可用標頭")
        else:
            head_error = FetchError(url, f"HEAD HTTP {status}")

    if gate is not None and hasattr(gate, "fell_back"):
        gate.fell_back = True
    head_reason = head_error.reason if head_error is not None else "HEAD 失敗"
    try:
        status, headers = _exchange(url, "GET", timeout, gate)
    except FetchError as exc:
        raise FetchError(url, f"{head_reason}；GET {exc.reason}") from exc
    if not (200 <= status < 300):
        raise FetchError(url, f"{head_reason}；GET HTTP {status}")
    return metadata_from_headers(headers)


def _call_fetch_meta(fetch_meta, url: str, timeout: float, gate: _CallGate):
    try:
        return fetch_meta(url, timeout=timeout, gate=gate)
    except TypeError as exc:
        # Test doubles often accept only the URL.
        message = str(exc)
        if "unexpected keyword" not in message and "positional argument" not in message:
            raise
        return fetch_meta(url)


def collect_file_metadata(
    urls: list[str],
    *,
    workers: int = HEADER_WORKERS,
    interval: float = HEADER_INTERVAL_SECONDS,
    timeout: float = HEADER_TIMEOUT_SECONDS,
    fetch_meta=fetch_header_metadata,
) -> tuple[dict[str, dict], list[tuple[str, str]], list[str]]:
    """Return (metadata by URL, errors, URLs that needed a GET fallback)."""
    if not urls:
        return {}, [], []
    results: dict[str, dict] = {}
    errors: list[tuple[str, str]] = []
    fallbacks: list[str] = []
    lock = threading.Lock()
    gate = RequestGate(interval)

    def wrapped(url: str) -> None:
        call_gate = _CallGate(gate)
        try:
            meta = _call_fetch_meta(fetch_meta, url, timeout, call_gate)
        except Exception as exc:  # noqa: BLE001
            reason = exc.reason if isinstance(exc, FetchError) else str(exc)
            with lock:
                errors.append((url, reason))
            return
        with lock:
            results[url] = clean_metadata(meta)
            if call_gate.fell_back:
                fallbacks.append(url)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(wrapped, urls))
    return results, errors, fallbacks


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_manifest(path: Path, links: dict[str, list[str]], files: dict[str, dict]) -> None:
    ordered_files = {url: clean_metadata(files[url]) for url in sorted(files)}
    payload = {"hubs": HUBS, "links": links, "files": ordered_files}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_hubs(fetch_html=fetch) -> tuple[dict[str, list[str]], dict[str, str]]:
    live: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for key, url in HUBS.items():
        try:
            live[key] = links_from(fetch_html(url))
        except Exception as exc:  # noqa: BLE001
            errors[key] = f"{key}: 下載失敗 {url} ({exc})"
            live[key] = []
    return live, errors


def unique_urls(groups: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for key in HUBS:
        for url in groups.get(key, []):
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found


def main(
    argv: list[str] | None = None,
    *,
    fetch_html=fetch,
    fetch_meta=fetch_header_metadata,
    manifest_path: Path | None = None,
    workers: int = HEADER_WORKERS,
    interval: float = HEADER_INTERVAL_SECONDS,
) -> int:
    if argv is None:
        argv = sys.argv[1:]
    write = "--write-manifest" in argv
    manifest_path = manifest_path or MANIFEST

    live, hub_errors = fetch_hubs(fetch_html)
    if write and hub_errors:
        for message in hub_errors.values():
            print("錯誤：", message)
        print("有頁面下載失敗，未寫入清單，避免整組連結被清走。")
        return 1

    urls = unique_urls(live)
    if urls:
        print(f"正在讀取 {len(urls)} 個檔案標頭（HEAD，失敗才改讀 GET 標頭）…")
    live_files, file_errors, fallbacks = collect_file_metadata(
        urls,
        workers=workers,
        interval=interval,
        fetch_meta=fetch_meta,
    )
    error_by_url = {url: reason for url, reason in file_errors}

    if write:
        previous_files: dict = {}
        if manifest_path.exists():
            try:
                previous_files = load_manifest(manifest_path).get("files") or {}
            except (OSError, json.JSONDecodeError):
                previous_files = {}
        files: dict[str, dict] = {}
        for url in urls:
            if url in live_files:
                files[url] = live_files[url]
            elif isinstance(previous_files.get(url), dict):
                files[url] = clean_metadata(previous_files[url])
        dump_manifest(manifest_path, live, files)
        print(f"已寫入 {manifest_path}（連結同檔案標頭）")
        for url in fallbacks:
            print(f"注意：HEAD 失敗，已改用 GET 讀標頭：{url}")
        if file_errors:
            for url, reason in file_errors:
                print(f"錯誤：讀取檔案標頭失敗 {url}（{reason}）")
            print("部分檔案未能讀到標頭。若清單裡原本有紀錄，已保留舊標頭。")
            return 1
        return 0

    if not manifest_path.exists():
        print("找不到 scripts/source-manifest.json。可先執行：python3 scripts/check_sources.py --write-manifest")
        return 1

    try:
        saved = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"錯誤：讀不到清單 {manifest_path} ({exc})")
        return 1

    previous: dict[str, list[str]] = saved.get("links") or {}
    saved_files = saved.get("files") if isinstance(saved.get("files"), dict) else {}
    print("搵服務 Find Service — 來源巡查")
    print("對照社署公開頁面上的 PDF／Excel／Word 連結，同本站上次收錄的清單。")
    print("同一網址會再用 HTTP 標頭（Last-Modified、ETag、Content-Length）睇檔案有冇被換走。")
    changed = False
    warned = False

    for key, url in HUBS.items():
        print(f"\n[{key}] {url}")
        if key in hub_errors:
            print(f"  {hub_errors[key]}")
            print("  頁面下載失敗，今次不會比較這組連結。")
            changed = True
            continue
        old = previous.get(key) or []
        new = live.get(key) or []
        added, removed = link_changes(old, new)
        print(f"  上次 {len(set(old))} 個檔，今次 {len(set(new))} 個檔")
        if added:
            changed = True
            print("  新增：")
            for item in added:
                print("   +", item)
        if removed:
            changed = True
            print("  消失：")
            for item in removed:
                print("   -", item)
        if not added and not removed:
            print("  連結沒有變動")

        old_set = set(old)
        header_matches = 0
        header_problems = 0
        hub_warned = False
        for item in new:
            if item in error_by_url:
                changed = True
                header_problems += 1
                print(f"  錯誤：讀取檔案標頭失敗 {item}（{error_by_url[item]}）")
                continue
            if item not in old_set:
                continue
            has_saved = isinstance(saved_files.get(item), dict)
            saved_meta = saved_files[item] if has_saved else None
            verdict = classify_metadata(saved_meta, live_files.get(item))
            status = verdict["status"]
            if status == "match":
                header_matches += 1
                continue
            if status == "changed":
                changed = True
                header_problems += 1
                fields = "、".join(change["field"] for change in verdict["changes"])
                print("  檔案標頭有變：")
                print("   !", item)
                print(f"     不同：{fields}")
                print(f"     上次：{format_metadata(saved_meta)}")
                print(f"     今次：{format_metadata(live_files.get(item))}")
                continue
            if status == "headers_gone":
                changed = True
                header_problems += 1
                print("  上次有標頭，今次沒有可用標頭：")
                print("   !", item)
                print(f"     上次：{format_metadata(saved_meta)}")
                print(f"     今次：{format_metadata(live_files.get(item))}")
                continue
            if status == "no_baseline":
                changed = True
                header_problems += 1
                print(f"  未能比對：清單未有這個網址的標頭基準：{item}")
                continue
            hub_warned = True
            warned = True
            if status == "gained_headers":
                print(f"  警告：上次沒有可用標頭，今次有，暫不當作檔案被換：{item}")
                print(f"    今次：{format_metadata(live_files.get(item))}")
            elif verdict["reason"] == "no_overlap":
                print(f"  警告：新舊標頭沒有重疊欄位，跳過：{item}")
                print(f"    上次：{format_metadata(saved_meta)}")
                print(f"    今次：{format_metadata(live_files.get(item))}")
            else:
                print(f"  警告：沒有可用標頭，跳過：{item}")
        if header_matches and not header_problems and not hub_warned:
            print(f"  檔案標頭沒有變動（{header_matches} 個）")
        elif header_matches:
            print(f"  其餘 {header_matches} 個檔案標頭沒有變動")

    for url in fallbacks:
        print(f"注意：HEAD 失敗，已改用 GET 讀標頭：{url}")

    if changed:
        print("\n有變動。請人工睇過新舊檔，再決定是否更新 scripts/source-manifest.json 同重跑 scripts/build_directory.py。")
        print("本腳本不會自動改名冊，亦不會部署網站。")
        return 1
    if warned:
        print("\n來源連結與可比較的檔案標頭都同清單一致。有部分網址因為沒有可用標頭而跳過，詳見上面警告。")
        return 0
    print("\n來源連結同檔案標頭都與清單一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
