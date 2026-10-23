"""Generate music playlists from tags and user-defined filters.

Copyright (C) 2024-2026 Fidel Ramos.
SPDX-License-Identifier: GPL-3.0-or-later

Genplis is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. It is distributed WITHOUT ANY WARRANTY; see LICENSE.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("genplis")
except PackageNotFoundError:
    # A raw source checkout has no installed distribution metadata.
    __version__ = "0+unknown"
