"""Validate argument vectors for local QGIS/PDAL helper processes."""
import os
import shutil


def validated_process_args(args):
    """Resolve an existing local executable and reject shell command strings."""
    if not isinstance(args, (list, tuple)) or not args:
        raise ValueError('A non-empty process argument list is required')
    argv = [os.fspath(arg) for arg in args]
    if any(not isinstance(arg, str) or '\x00' in arg for arg in argv):
        raise ValueError('Process arguments must be strings without NUL characters')
    executable = argv[0]
    if not os.path.isfile(executable):
        executable = shutil.which(executable)
    if not executable or not os.path.isfile(executable):
        raise FileNotFoundError('Local helper executable was not found')
    argv[0] = os.path.abspath(executable)
    return argv
