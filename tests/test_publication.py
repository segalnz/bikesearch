from check_publication import check, inspect

from motorcycle_monitor.secrets import credential


def test_publication_rejects_credentials_without_showing_values():
    token = "ghp_" + "A" * 36
    findings = inspect("README.md", token.encode(), [])
    assert findings and token not in str(findings)
    assert inspect("tokens.txt", b"not-a-real-token", [])
    assert inspect(".env", b"PASSWORD=test", [])
    assert not inspect(".env.example", b"PASSWORD=", [])


def test_publication_compares_local_secret_material(tmp_path):
    token = "sk-" + "B" * 36
    (tmp_path / "token.txt").write_text(token)
    (tmp_path / "README.md").write_text("Accidentally copied " + token)
    count, findings = check(tmp_path)
    assert count == 1 and findings and token not in str(findings)


def test_mixed_credentials_load_only_requested_key(tmp_path):
    deepseek = "sk-" + "D" * 36
    github = "ghp_" + "G" * 36
    path = tmp_path / "token.txt"
    path.write_text("DeepSeek\n" + deepseek + "\nGitHub\n" + github)
    assert credential("DEEPSEEK_API_KEY", str(path)) == deepseek
    assert credential("GITHUB_TOKEN", str(path)) == github


def test_invalid_url_does_not_echo_embedded_credentials():
    import pytest

    from motorcycle_monitor.normalization import safe_url

    password = "private-example-password"
    with pytest.raises(ValueError) as error:
        safe_url("https://user:" + password + "@dealer.co.nz/bike", ["dealer.co.nz"])
    assert password not in str(error.value)
