"""GitHub Releases uzerinden guncelleme.

En kritik davranis surum karsilastirmasi: yanlis karsilastirma ya kullaniciyi
bos yere guncellemeye cagirir ya da gercek bir guncellemeyi gizler.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from palaskript import updates


class TestVersionParsing:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1.2.3", (1, 2, 3)),
            ("v1.2.3", (1, 2, 3)),
            ("V10.0.1", (10, 0, 1)),
            ("v2.0.0-beta.1", (2, 0, 0)),
            ("Palaskript 1.4.2", (1, 4, 2)),
        ],
    )
    def test_parses_common_forms(self, text: str, expected: tuple[int, int, int]):
        assert updates.parse_version(text) == expected

    @pytest.mark.parametrize("text", ["", "surum yok", "1.2", "abc"])
    def test_rejects_unparseable(self, text: str):
        assert updates.parse_version(text) is None


class TestIsNewer:
    @pytest.mark.parametrize(
        ("candidate", "current"),
        [("1.0.1", "1.0.0"), ("1.1.0", "1.0.9"), ("2.0.0", "1.9.9"), ("v1.0.1", "1.0.0")],
    )
    def test_detects_newer(self, candidate: str, current: str):
        assert updates.is_newer(candidate, current)

    @pytest.mark.parametrize(
        ("candidate", "current"),
        [("1.0.0", "1.0.0"), ("1.0.0", "1.0.1"), ("1.9.9", "2.0.0")],
    )
    def test_rejects_same_or_older(self, candidate: str, current: str):
        assert not updates.is_newer(candidate, current)

    def test_compares_numerically_not_alphabetically(self):
        """Metin karsilastirmasi 10'u 9'dan kucuk sayardi."""
        assert updates.is_newer("1.10.0", "1.9.0")
        assert not updates.is_newer("1.9.0", "1.10.0")

    def test_unparseable_is_never_newer(self):
        """Bilinmeyen bir etiket yuzunden kullaniciyi guncellemeye cagirmayalim."""
        assert not updates.is_newer("bilinmiyor", "1.0.0")
        assert not updates.is_newer("1.0.1", "bilinmiyor")

    def test_defaults_to_the_running_version(self):
        """current verilmezse calisan surum kullanilmali."""
        assert not updates.is_newer(updates.__version__)
        assert updates.is_newer("999.0.0")

    def test_running_version_is_read_at_call_time(self, monkeypatch):
        """Varsayilan imzada baglanmis olsaydi bu taklit calismazdi ve
        fonksiyon test edilemez olurdu."""
        monkeypatch.setattr(updates, "__version__", "0.9.0")
        assert updates.is_newer("1.0.0")
        monkeypatch.setattr(updates, "__version__", "2.0.0")
        assert not updates.is_newer("1.0.0")


def _release_payload(tag: str = "v1.2.0", *, with_installer: bool = True) -> dict:
    assets = []
    if with_installer:
        assets = [
            {
                "name": f"Palaskript-Setup-{tag.lstrip('v')}.exe",
                "browser_download_url": "https://example.invalid/setup.exe",
                "size": 101_000_000,
            },
            {
                "name": f"Palaskript-Setup-{tag.lstrip('v')}.exe.sha256",
                "browser_download_url": "https://example.invalid/setup.exe.sha256",
                "size": 90,
            },
        ]
    return {"tag_name": tag, "body": "Yenilikler", "assets": assets}


class TestFetchLatest:
    def test_reads_tag_and_assets(self, monkeypatch):
        monkeypatch.setattr(updates, "_get_json", lambda url: _release_payload())
        release = updates.fetch_latest("ornek/depo")
        assert release.version == "1.2.0"
        assert release.installer_name.endswith(".exe")
        assert release.checksum_url.endswith(".sha256")
        assert release.can_install

    def test_release_without_installer_is_flagged(self, monkeypatch):
        monkeypatch.setattr(
            updates, "_get_json", lambda url: _release_payload(with_installer=False)
        )
        release = updates.fetch_latest("ornek/depo")
        assert not release.can_install

    def test_ignores_non_installer_assets(self, monkeypatch):
        payload = _release_payload()
        payload["assets"].append(
            {
                "name": "kaynak.zip",
                "browser_download_url": "https://example.invalid/kaynak.zip",
                "size": 10,
            }
        )
        monkeypatch.setattr(updates, "_get_json", lambda url: payload)
        assert updates.fetch_latest("ornek/depo").installer_name.endswith(".exe")

    @pytest.mark.parametrize("repo", ["", "eksik-bolu", None])
    def test_rejects_unset_repo(self, repo):
        """Depo ayarlanmamissa sessizce baska bir depoyu denemeyelim."""
        with pytest.raises(updates.UpdateError):
            updates.fetch_latest(repo or "")


class TestCheck:
    def test_returns_release_when_newer(self, monkeypatch):
        monkeypatch.setattr(updates, "_get_json", lambda url: _release_payload("v99.0.0"))
        assert updates.check("ornek/depo") is not None

    def test_returns_none_when_current(self, monkeypatch):
        monkeypatch.setattr(
            updates, "_get_json", lambda url: _release_payload(f"v{updates.__version__}")
        )
        assert updates.check("ornek/depo") is None


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class TestChecksum:
    @pytest.mark.parametrize(
        "body",
        [
            b"aaaa  Palaskript-Setup-1.0.0.exe\n",
            b"aaaa *Palaskript-Setup-1.0.0.exe\n",
            b"aaaa\n",
            b"  AAAA  dosya.exe  ",
        ],
    )
    def test_reads_sha256sum_format(self, monkeypatch, body: bytes):
        """sha256sum ciktisi ve yalin ozet, ikisi de kabul edilmeli."""
        monkeypatch.setattr(
            updates.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(body)
        )
        assert updates._expected_checksum("https://example.invalid/x.sha256") == "aaaa"

    def test_network_failure_returns_none(self, monkeypatch):
        import urllib.error

        def boom(req, timeout=None):
            raise urllib.error.URLError("ag yok")

        monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
        assert updates._expected_checksum("https://example.invalid/x.sha256") is None

    def test_hashes_a_file(self, tmp_path):
        path = tmp_path / "dosya.bin"
        path.write_bytes(b"palaskript")
        assert updates._sha256(path) == hashlib.sha256(b"palaskript").hexdigest()


class TestDownloadVerification:
    def test_rejects_a_file_whose_checksum_does_not_match(self, monkeypatch, tmp_path):
        """Yarim inmis bir kurulum dosyasini calistirmak bozuk kuruluma yol acar."""
        release = updates.Release(
            version="9.9.9",
            tag="v9.9.9",
            notes="",
            installer_url="https://example.invalid/setup.exe",
            installer_name="Palaskript-Setup-9.9.9.exe",
            installer_size=10,
            checksum_url="https://example.invalid/setup.exe.sha256",
        )

        def fake_download(url, target, expected_size, progress):
            target.write_bytes(b"yarim")

        monkeypatch.setattr(updates, "_download", fake_download)
        monkeypatch.setattr(updates, "_expected_checksum", lambda url: "b" * 64)
        monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))

        with pytest.raises(updates.UpdateError) as excinfo:
            updates.download_installer(release)
        assert "doğrulanamadı" in str(excinfo.value)
        assert not (tmp_path / release.installer_name).exists()

    def test_accepts_a_matching_file(self, monkeypatch, tmp_path):
        payload = b"gercek kurulum"
        release = updates.Release(
            version="9.9.9",
            tag="v9.9.9",
            notes="",
            installer_url="https://example.invalid/setup.exe",
            installer_name="Palaskript-Setup-9.9.9.exe",
            installer_size=len(payload),
            checksum_url="https://example.invalid/setup.exe.sha256",
        )

        def fake_download(url, target, expected_size, progress):
            target.write_bytes(payload)

        monkeypatch.setattr(updates, "_download", fake_download)
        monkeypatch.setattr(
            updates, "_expected_checksum", lambda url: hashlib.sha256(payload).hexdigest()
        )
        monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))

        assert updates.download_installer(release).exists()

    def test_falls_back_to_size_check_without_checksum(self, monkeypatch, tmp_path):
        release = updates.Release(
            version="9.9.9",
            tag="v9.9.9",
            notes="",
            installer_url="https://example.invalid/setup.exe",
            installer_name="Palaskript-Setup-9.9.9.exe",
            installer_size=100,
            checksum_url=None,
        )
        monkeypatch.setattr(
            updates, "_download", lambda url, target, size, progress: target.write_bytes(b"kisa")
        )
        monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))

        with pytest.raises(updates.UpdateError):
            updates.download_installer(release)


class TestApiErrors:
    def test_missing_release_gives_a_readable_message(self, monkeypatch):
        import urllib.error

        def raise_404(url, timeout=None):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        monkeypatch.setattr(updates.urllib.request, "urlopen", raise_404)
        with pytest.raises(updates.UpdateError) as excinfo:
            updates.fetch_latest("ornek/depo")
        assert "yayınlanmış" in str(excinfo.value)

    def test_rate_limit_gives_a_readable_message(self, monkeypatch):
        import urllib.error

        def raise_403(url, timeout=None):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        monkeypatch.setattr(updates.urllib.request, "urlopen", raise_403)
        with pytest.raises(updates.UpdateError) as excinfo:
            updates.fetch_latest("ornek/depo")
        assert "sınırına" in str(excinfo.value)


def test_json_payload_shape_is_what_github_returns():
    """Testlerdeki sahte yanit gercek API bicimiyle ayni alanlari tasimali."""
    payload = json.loads(json.dumps(_release_payload()))
    assert {"tag_name", "body", "assets"} <= set(payload)
    assert {"name", "browser_download_url", "size"} <= set(payload["assets"][0])
