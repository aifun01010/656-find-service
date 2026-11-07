#!/usr/bin/env python3
"""Offline checks for source-link and HTTP header drift detection."""

from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import check_sources as sources


def meta(last_modified=None, etag=None, content_length=None) -> dict:
    return {"lastModified": last_modified, "etag": etag, "contentLength": content_length}


class ClassifyTests(unittest.TestCase):
    def test_same_headers_match_when_etag_is_missing(self) -> None:
        saved = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 310675)
        live = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 310675)
        verdict = sources.classify_metadata(saved, live)
        self.assertEqual(verdict["status"], "match")
        self.assertFalse(sources.status_is_failure(verdict["status"]))

    def test_equivalent_http_dates_and_numeric_length_match(self) -> None:
        saved = meta("Wed, 15 Oct 2025 02:07:47 GMT", '"abc"', "42")
        live = meta("15 Oct 2025 02:07:47 GMT", '"abc"', 42)
        self.assertEqual(sources.classify_metadata(saved, live)["status"], "match")

    def test_content_length_change_is_drift(self) -> None:
        saved = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10)
        live = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 11)
        verdict = sources.classify_metadata(saved, live)
        self.assertEqual(verdict["status"], "changed")
        self.assertEqual(verdict["changes"][0]["field"], "contentLength")
        self.assertTrue(sources.status_is_failure(verdict["status"]))

    def test_last_modified_and_etag_changes_are_drift(self) -> None:
        saved = meta("Wed, 15 Oct 2025 02:07:47 GMT", '"old"', 10)
        live = meta("Thu, 16 Oct 2025 02:07:47 GMT", '"new"', 10)
        fields = {change["field"] for change in sources.classify_metadata(saved, live)["changes"]}
        self.assertEqual(fields, {"lastModified", "etag"})

    def test_one_missing_header_does_not_false_positive(self) -> None:
        saved = meta("Wed, 15 Oct 2025 02:07:47 GMT", '"abc"', 10)
        live = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10)
        self.assertEqual(sources.classify_metadata(saved, live)["status"], "match")

    def test_no_usable_headers_on_either_side_is_a_skip(self) -> None:
        verdict = sources.classify_metadata(meta(), meta())
        self.assertEqual(verdict["status"], "skip")
        self.assertFalse(sources.status_is_failure(verdict["status"]))

    def test_headers_that_disappear_are_drift(self) -> None:
        verdict = sources.classify_metadata(meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10), meta())
        self.assertEqual(verdict["status"], "headers_gone")
        self.assertTrue(sources.status_is_failure(verdict["status"]))

    def test_newly_available_headers_do_not_fail(self) -> None:
        verdict = sources.classify_metadata(meta(), meta(content_length=10))
        self.assertEqual(verdict["status"], "gained_headers")
        self.assertFalse(sources.status_is_failure(verdict["status"]))

    def test_no_overlap_does_not_fail(self) -> None:
        saved = meta(etag='"only-old"')
        live = meta(content_length=10)
        verdict = sources.classify_metadata(saved, live)
        self.assertEqual(verdict["status"], "skip")
        self.assertEqual(verdict["reason"], "no_overlap")

    def test_missing_manifest_entry_blocks_comparison(self) -> None:
        verdict = sources.classify_metadata(None, meta(content_length=10))
        self.assertEqual(verdict["status"], "no_baseline")
        self.assertTrue(sources.status_is_failure(verdict["status"]))

    def test_header_parser_is_case_insensitive(self) -> None:
        parsed = sources.metadata_from_headers(
            {"Last-Modified": " Wed, 15 Oct 2025 02:07:47 GMT ", "ETAG": "", "Content-Length": "12"}
        )
        self.assertEqual(parsed["lastModified"], "Wed, 15 Oct 2025 02:07:47 GMT")
        self.assertIsNone(parsed["etag"])
        self.assertEqual(parsed["contentLength"], 12)

    def test_link_changes_ignore_order(self) -> None:
        added, removed = sources.link_changes(["b", "a"], ["a", "c"])
        self.assertEqual(added, ["c"])
        self.assertEqual(removed, ["b"])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:
        self._respond(include_body=False)

    def do_GET(self) -> None:
        self._respond(include_body=True)

    def _respond(self, include_body: bool) -> None:
        path = urllib.parse.urlparse(self.path).path
        self.server.events.append((self.command, path))  # type: ignore[attr-defined]
        if path == "/ok":
            body = b"hello"
            self.send_response(200)
            self.send_header("Last-Modified", "Wed, 15 Oct 2025 02:07:47 GMT")
            self.send_header("ETag", '"abc"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if include_body:
                self.wfile.write(body)
            return
        if path == "/no-head":
            if self.command == "HEAD":
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Last-Modified", "Thu, 16 Oct 2025 00:00:00 GMT")
            self.send_header("ETag", '"from-get"')
            self.send_header("Content-Length", "999999")
            self.end_headers()
            # Headers are already on the wire. A client that waits for the body stalls here.
            time.sleep(2)
            try:
                self.wfile.write(b"x" * 100)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return
        if path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/go":
            port = self.server.server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return


class HeaderFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.events = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_head_success_does_not_get(self) -> None:
        parsed = sources.fetch_header_metadata(self.base + "/ok", timeout=5)
        self.assertEqual(parsed["contentLength"], 5)
        self.assertEqual(parsed["etag"], '"abc"')
        self.assertNotIn(("GET", "/ok"), self.httpd.events)

    def test_head_rejection_uses_get_headers_without_the_body(self) -> None:
        started = time.monotonic()
        parsed = sources.fetch_header_metadata(self.base + "/no-head", timeout=5)
        elapsed = time.monotonic() - started
        self.assertEqual(parsed["etag"], '"from-get"')
        self.assertEqual(parsed["contentLength"], 999999)
        self.assertLess(elapsed, 1.5)
        self.assertIn(("HEAD", "/no-head"), self.httpd.events)
        self.assertIn(("GET", "/no-head"), self.httpd.events)

    def test_missing_file_does_not_fall_back_to_get(self) -> None:
        with self.assertRaises(sources.FetchError):
            sources.fetch_header_metadata(self.base + "/missing", timeout=5)
        self.assertIn(("HEAD", "/missing"), self.httpd.events)
        self.assertNotIn(("GET", "/missing"), self.httpd.events)

    def test_redirect_is_followed(self) -> None:
        parsed = sources.fetch_header_metadata(self.base + "/go", timeout=5)
        self.assertEqual(parsed["etag"], '"abc"')
        self.assertIn(("HEAD", "/go"), self.httpd.events)
        self.assertIn(("HEAD", "/ok"), self.httpd.events)


PDF = "https://www.swd.gov.hk/storage/asset/section/733/a.pdf"
OTHER = "https://www.swd.gov.hk/storage/asset/section/290/tc/b.pdf"


def baseline(url: str = PDF, **overrides) -> dict:
    record = meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10)
    record.update(overrides)
    return {
        "hubs": sources.HUBS,
        "links": {"csse": [url], "ccse": [], "mss": [], "ifsc": []},
        "files": {url: record},
    }


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.manifest = Path(self._tmp.name) / "source-manifest.json"

    def _run(self, argv: list[str], html: dict, live_meta: dict[str, dict] | None = None, errors: set[str] | None = None) -> tuple[int, str]:
        errors = errors or set()

        def fetch_html(url: str) -> str:
            value = html.get(url, "<html></html>")
            if isinstance(value, BaseException):
                raise value
            return value

        def fetch_meta(url: str, timeout: float = 20, gate=None) -> dict:
            if gate is not None:
                gate.wait()
            if url in errors:
                raise sources.FetchError(url, "HTTP 500")
            return (live_meta or {}).get(url, meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10))

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = sources.main(
                argv,
                fetch_html=fetch_html,
                fetch_meta=fetch_meta,
                manifest_path=self.manifest,
                workers=2,
                interval=0,
            )
        return code, stdout.getvalue()

    def test_matching_headers_exit_zero(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'})
        self.assertEqual(code, 0, output)
        self.assertIn("檔案標頭沒有變動", output)
        self.assertIn("來源連結同檔案標頭都與清單一致", output)

    def test_same_url_with_new_length_exits_one(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        code, output = self._run(
            [],
            {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'},
            {PDF: meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 99)},
        )
        self.assertEqual(code, 1, output)
        self.assertIn("檔案標頭有變", output)
        self.assertIn("contentLength", output)
        self.assertIn("上次：", output)
        self.assertIn("今次：", output)
        self.assertIn("contentLength=10", output)
        self.assertIn("contentLength=99", output)

    def test_missing_baseline_exits_one(self) -> None:
        payload = baseline()
        payload["files"] = {}
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'})
        self.assertEqual(code, 1, output)
        self.assertIn("標頭基準", output)

    def test_absent_headers_are_skipped_when_never_present(self) -> None:
        payload = baseline()
        payload["files"][PDF] = meta()
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'}, {PDF: meta()})
        self.assertEqual(code, 0, output)
        self.assertIn("沒有可用標頭，跳過", output)

    def test_disappeared_headers_exit_one(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'}, {PDF: meta()})
        self.assertEqual(code, 1, output)
        self.assertIn("今次沒有可用標頭", output)

    def test_added_link_exits_one_without_calling_it_metadata_drift(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        html = f'<a href="{PDF}">a</a><a href="{OTHER}">b</a>'
        code, output = self._run([], {sources.HUBS["csse"]: html})
        self.assertEqual(code, 1, output)
        self.assertIn("新增", output)
        self.assertIn(OTHER, output)
        self.assertNotIn(f"檔案標頭有變：\n   ! {OTHER}", output)

    def test_hub_fetch_error_does_not_pretend_files_were_removed(self) -> None:
        payload = baseline(OTHER)
        payload["links"] = {"csse": [], "ccse": [], "mss": [OTHER], "ifsc": []}
        payload["files"] = {OTHER: meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10)}
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["mss"]: TimeoutError("timed out")})
        self.assertEqual(code, 1, output)
        self.assertIn("下載失敗", output)
        self.assertNotIn("消失", output)
        self.assertNotIn("- " + OTHER, output)

    def test_file_fetch_error_exits_one(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        code, output = self._run([], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'}, errors={PDF})
        self.assertEqual(code, 1, output)
        self.assertIn("讀取檔案標頭失敗", output)

    def test_write_manifest_records_headers(self) -> None:
        code, output = self._run(
            ["--write-manifest"],
            {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'},
            {PDF: meta("Wed, 15 Oct 2025 02:07:47 GMT", None, 10)},
        )
        self.assertEqual(code, 0, output)
        saved = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(saved["links"]["csse"], [PDF])
        self.assertEqual(
            saved["files"][PDF],
            {"lastModified": "Wed, 15 Oct 2025 02:07:47 GMT", "etag": None, "contentLength": 10},
        )

    def test_write_manifest_keeps_old_headers_when_a_read_fails(self) -> None:
        self.manifest.write_text(json.dumps(baseline()), encoding="utf-8")
        code, _output = self._run(["--write-manifest"], {sources.HUBS["csse"]: f'<a href="{PDF}">a</a>'}, errors={PDF})
        self.assertEqual(code, 1)
        saved = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(saved["files"][PDF]["contentLength"], 10)

    def test_write_manifest_does_not_clobber_when_a_hub_fails(self) -> None:
        self.manifest.write_text('{"keep": true}\n', encoding="utf-8")
        code, output = self._run(["--write-manifest"], {sources.HUBS["csse"]: TimeoutError("timed out")})
        self.assertEqual(code, 1, output)
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), '{"keep": true}\n')
        self.assertIn("未寫入清單", output)


if __name__ == "__main__":
    unittest.main()
