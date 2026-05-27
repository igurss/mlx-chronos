import pytest
import sys
from unittest.mock import patch
from argparse import Namespace
from mlx_chronos.cli import cmd_run, main

def test_cmd_run_invalid_trials(capsys):
    args = Namespace(trials=0, ram_sample_interval=0.1)
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --trials must be at least 1." in capsys.readouterr().err

def test_cmd_run_invalid_ram_interval(capsys):
    args = Namespace(trials=1, ram_sample_interval=0)
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --ram-sample-interval must be greater than 0." in capsys.readouterr().err

def test_main_engines_command():
    with patch.object(sys, "argv", ["mlx-chronos", "engines"]):
        with patch("mlx_chronos.cli.cmd_engines") as mock_engines:
            main()
            mock_engines.assert_called_once()
