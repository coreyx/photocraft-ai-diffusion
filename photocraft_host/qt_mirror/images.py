"""Icons and pictures sent to PhotoCraft once each, by content hash (``image.put``), and named in
widget props as ``"image:<hash>"``."""

from __future__ import annotations

import hashlib
from typing import Any

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QIcon, QImage, QPixmap

#: Pixel size icons are rendered at: large enough for PhotoCraft to scale down sharply.
ICON_SIZE = 32


class ImageCache:
    """Uploads each distinct picture once per connection and remembers its reference."""

    def __init__(self, transport: Any):
        self._transport = transport
        self._sent: set[str] = set()
        self._icons: dict[int, str | None] = {}

    def icon(self, icon: QIcon | None, size: int = ICON_SIZE) -> str | None:
        """A reference for ``icon``, or ``None`` when it is empty."""
        if icon is None or icon.isNull():
            return None
        key = icon.cacheKey()
        if key not in self._icons:
            pixmap = icon.pixmap(size, size)
            self._icons[key] = None if pixmap.isNull() else self.image(pixmap)
        return self._icons[key]

    def image(self, picture: QPixmap | QImage) -> str:
        """A reference for ``picture``, uploading it the first time it is seen."""
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        picture.save(buffer, "PNG")
        png = bytes(data.data())
        digest = hashlib.sha256(png).hexdigest()[:32]
        if digest not in self._sent:
            self._transport.call("image.put", {"hash": digest, "encoding": "png"}, png)
            self._sent.add(digest)
        return f"image:{digest}"
