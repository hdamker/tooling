"""Intentional failure for the temporary Tooling CI negative-test PR."""


def test_negative_release_automation_probe():
    assert False, "intentional release automation pytest failure for Tooling CI negative test"
