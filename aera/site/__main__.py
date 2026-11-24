import sys
from .cli import main

if __name__ == "__main__":          # without this guard, worker processes started by --calibrate would each re-run the command line
    sys.exit(main())
