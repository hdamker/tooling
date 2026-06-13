"""Intentional failure for the temporary Tooling CI negative-test PR."""


def test_negative_validation_probe():
    assert False, "intentional validation pytest failure for Tooling CI negative test"
