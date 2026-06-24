# conftest.py for verify_tests — loads the tests.optional plugin
# so pytest does not error on the "optional-tests" config key.
pytest_plugins = ["tests.optional"]
