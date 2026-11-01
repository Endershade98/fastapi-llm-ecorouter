from importlib import import_module


def test_domain_package_is_importable() -> None:
    module = import_module("eco_router.domain")
    assert module is not None


def test_application_package_is_importable() -> None:
    module = import_module("eco_router.application")
    assert module is not None


def test_infrastructure_package_is_importable() -> None:
    module = import_module("eco_router.infrastructure")
    assert module is not None


def test_entrypoints_package_is_importable() -> None:
    module = import_module("eco_router.entrypoints")
    assert module is not None
