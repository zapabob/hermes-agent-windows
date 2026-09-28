"""Select one parameterized mutant case without losing canonical-runner isolation."""
import ast
import os
from pathlib import Path
import runpy

from verification_v2 import main as prepare, replace_once


def main():
    prepare()
    path = Path('.n53-verification/verify.py')
    source = path.read_text(encoding='utf-8')
    before = "    command = [str(BASH), 'scripts/run_tests.sh', target, '-q', f'--junitxml=n53-evidence/{label}.xml']"
    after = '''    file_target, separator, selector = target.partition("::")
    selection = []
    if separator:
        # The upstream runner converts node IDs to function-only -k selectors,
        # dropping the parameter. An explicit -k is required for exactly ONE case.
        name, bracket, parameter = selector.partition("[")
        if not name.replace("_", "").isalnum():
            raise RuntimeError("Unsupported mutation selector")
        expression = name
        if bracket:
            parameter = parameter.removesuffix("]")
            if not parameter.replace("_", "").isalnum():
                raise RuntimeError("Unsupported mutation parameter")
            expression += " and " + parameter
        selection = ["-k", expression]
    command = [str(BASH), 'scripts/run_tests.sh', file_target, '-q', f'--junitxml=n53-evidence/{label}.xml', *selection]'''
    source = replace_once(source, before, after)
    ast.parse(source)
    path.write_bytes(source.encode('utf-8'))
    # Keep every observation single-attempt; a flaky retry cannot hide a failure.
    os.environ['HERMES_TEST_FILE_RETRIES'] = '0'
    runpy.run_path(str(path), run_name='__main__')


if __name__ == '__main__':
    main()
