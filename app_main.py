"""Entry point of the Mac app (used by py2app)."""

import sys

# Never write .pyc files into the app bundle: that would break its code signature. The build
# script precompiles everything, so nothing is lost.
sys.dont_write_bytecode = True

from anonymizer.app import main  # noqa: E402

main()
