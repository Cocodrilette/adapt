import os

from uvicorn import Config

from adapt.commands import serve


def test_reload_uses_uvicorn_reload_supervisor_and_factory(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.delenv(serve._RELOAD_OPTIONS_ENV, raising=False)

    def capture_run(**kwargs):
        captured.update(kwargs)
        app = serve.create_reload_app()
        assert app.state.config.root == tmp_path
        assert app.state.config.readonly is True

    monkeypatch.setattr(serve.uvicorn, "run", capture_run)

    serve.run_serve(
        root=tmp_path,
        host=None,
        port=None,
        tls_cert=None,
        tls_key=None,
        reload=True,
        readonly=True,
        debug=None,
    )

    uvicorn_config = Config(
        app=captured["app"],
        reload=captured["reload"],
        reload_dirs=captured["reload_dirs"],
        factory=captured["factory"],
    )
    assert uvicorn_config.should_reload is True
    assert captured["app"] == "adapt.commands.serve:create_reload_app"
    assert captured["reload_dirs"] == [str(tmp_path)]
    assert serve._RELOAD_OPTIONS_ENV not in os.environ
