"""Runs the browser-side barge-in harness under pytest.

The playback state machine is the one piece of this app that cannot be reasoned about
safely: it produced a bug that looked like the model truncating its own sentences, when
in fact the server had sent every byte and the browser threw the middle away. Skipped
when node is unavailable rather than failing the Python suite.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_bargein_drops_the_rest_of_a_cut_turn():
    r = subprocess.run(["node", "tests/frontend/bargein_test.js"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL PASS" in r.stdout
