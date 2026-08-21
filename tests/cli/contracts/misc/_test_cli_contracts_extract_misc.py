from tests.cli.contracts.misc._test_cli_contracts_extract_misc_common import *  # noqa: F403
from tests.cli.contracts.misc._test_cli_contracts_extract_misc_detect import *  # noqa: F403
from tests.cli.contracts.misc._test_cli_contracts_extract_misc_ops import *  # noqa: F403
from tests.cli.contracts.misc._test_cli_contracts_extract_misc_scopes import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]
