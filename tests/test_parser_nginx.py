from __future__ import annotations

from repo_analyzer.parsers.nginx import parse_nginx


def test_listen_and_location(golden_repo):
    cfg = parse_nginx((golden_repo / "frontend/nginx.conf").read_text(), "frontend/nginx.conf")
    listen = cfg.find("listen")
    assert listen[0].args == ["80"]
    assert listen[0].start_line == 2
    location = cfg.find("location")
    assert location[0].args == ["/"]
    assert location[0].context == ("server",)


def test_return_directive_in_extra_conf(golden_repo):
    cfg = parse_nginx(
        (golden_repo / "frontend/nginx-backend-not-found.conf").read_text(),
        "frontend/nginx-backend-not-found.conf",
    )
    returns = cfg.find("return")
    assert [r.args for r in returns] == [["404"], ["404"], ["404"]]


def test_unbalanced_brace_reported():
    cfg = parse_nginx("server {\n  listen 80;\n", "n.conf")
    assert any(i.construct == "nginx_brace" for i in cfg.issues)
