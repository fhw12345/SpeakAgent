import importlib

def test_server_package_importable():
    mod = importlib.import_module("server")
    assert mod is not None
