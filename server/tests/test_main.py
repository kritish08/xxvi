import logging

import xxvi.main as main_module
from xxvi.main import create_app, lifespan


async def test_lifespan_warns_loudly_when_serving_example_content(sessionmaker, monkeypatch, caplog):
    # Ship-blocking finding (task-30 review): a missing config/run.yaml
    # made get_config() silently fall back to run.example.yaml with no
    # warning anywhere -- not in a log, not in a health check. This proves
    # the app now logs a clear warning at startup in exactly that case.
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(main_module, "is_serving_example_content", lambda: True)
    app = create_app()
    with caplog.at_level(logging.WARNING, logger="xxvi.main"):
        async with lifespan(app):
            pass
    assert any("run.example.yaml" in record.message for record in caplog.records)


async def test_lifespan_is_quiet_when_a_real_config_is_present(sessionmaker, monkeypatch, caplog):
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(main_module, "is_serving_example_content", lambda: False)
    app = create_app()
    with caplog.at_level(logging.WARNING, logger="xxvi.main"):
        async with lifespan(app):
            pass
    assert not any("run.example.yaml" in record.message for record in caplog.records)


async def test_the_example_content_warning_does_not_claim_the_demo_is_unplayable(
    sessionmaker, monkeypatch, caplog
):
    # The old wording ("The run WILL NOT be completable like this") described
    # placeholder content. The example is now a real playable demo, so that
    # sentence became false -- and it is the first thing anyone running this
    # from a clone sees in their logs.
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(main_module, "is_serving_example_content", lambda: True)
    app = create_app()
    with caplog.at_level(logging.WARNING, logger="xxvi.main"):
        async with lifespan(app):
            pass
    text = " ".join(record.message for record in caplog.records)
    assert "WILL NOT be completable" not in text
    # The existing test at the top of this file still requires the filename,
    # so the rewrite must keep it.
    assert "run.example.yaml" in text
    assert "demo" in text.lower()
