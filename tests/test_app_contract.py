"""Verify the independently versioned macOS interface against the real CLI."""
import argparse
from unittest.mock import patch

import pytest

from mlx_chronos import cli
from mlx_chronos.app_contract import APP_CONTRACT, describe_app_contract


def test_contract_commands_match_the_real_cli_parser():
    class CapturedParser(Exception):
        pass

    def capture(parser, *args, **kwargs):
        commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        assert set(commands.choices) == set(APP_CONTRACT["supported_commands"])
        raise CapturedParser

    with patch.object(argparse.ArgumentParser, "parse_args", capture), pytest.raises(CapturedParser):
        cli.main()


def test_contract_description_cannot_mutate_shared_capabilities():
    contract = describe_app_contract()
    contract["required_capabilities"].clear()
    contract["supported_commands"].append("unsupported-command")
    assert describe_app_contract() == APP_CONTRACT
    assert APP_CONTRACT["required_capabilities"]
