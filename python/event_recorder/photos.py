"""
Crew photos (FR-29): what is kept of a photo uploaded from a phone, and when
it was taken.

Kept per photo, beside each other in uploads/<recording>/:
- the original, untouched
- a web copy, at most 2048 px, the right way up, JPEG: what goes to WordPress
- a thumbnail, at most 400 px, in thumbs/, for the event page

A phone's own clock is usually right, where the Pi's may not be, so the time
the photo says it was taken places it among the notes and the story. EXIF
gives a local time with no zone; it is read as Perth's (+8, which has no
daylight saving), the same explicit offset the racing app uses, never the
container's TZ, unless the photo carries its own offset.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

WEB_SIZE = 2048
THUMB_SIZE = 400
BOAT_OFFSET = timedelta(hours=8)

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_OFFSET_TIME_ORIGINAL = 36881
_DATETIME = 306


def web_name(original: Path) -> Path:
    return original.with_name(original.stem + '_web.jpg')


def thumb_path(image_path: Path) -> Path:
    """The thumbnail of a photo, from its web copy's path (or the original's)."""
    stem = image_path.stem[:-4] if image_path.stem.endswith('_web') else image_path.stem
    return image_path.parent / 'thumbs' / (stem + '.jpg')


def prepare(original: Path) -> Dict:
    """
    Make the web copy and the thumbnail of an uploaded photo, and read when
    it was taken.

    Returns:
        {'web': Path, 'thumb': Path or None, 'taken_at': naive UTC datetime
        or None}. A file Pillow cannot read (a HEIC from a phone that did not
        convert it) is kept as it is: its own web copy, with no thumbnail.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(original) as image:
            taken_at = _taken_at(image)
            upright = ImageOps.exif_transpose(image)
            if upright.mode not in ('RGB', 'L'):
                upright = upright.convert('RGB')

            web = web_name(original)
            copy = upright.copy()
            copy.thumbnail((WEB_SIZE, WEB_SIZE))
            copy.save(web, 'JPEG', quality=85, optimize=True)

            thumb = thumb_path(web)
            thumb.parent.mkdir(exist_ok=True)
            small = upright.copy()
            small.thumbnail((THUMB_SIZE, THUMB_SIZE))
            small.save(thumb, 'JPEG', quality=80)

        return {'web': web, 'thumb': thumb, 'taken_at': taken_at}
    except Exception as e:
        logger.warning(f"Could not prepare {original.name}, keeping it as uploaded: {e}")
        return {'web': original, 'thumb': None, 'taken_at': None}


def _taken_at(image) -> Optional[datetime]:
    try:
        exif = image.getexif()
        detail = exif.get_ifd(_EXIF_IFD) if hasattr(exif, 'get_ifd') else {}
        stamp = detail.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
        if not stamp:
            return None
        local = datetime.strptime(str(stamp).strip(), '%Y:%m:%d %H:%M:%S')
        offset = _offset(detail.get(_OFFSET_TIME_ORIGINAL))
        return (local - offset).replace(tzinfo=None)
    except Exception as e:
        logger.debug(f"No usable EXIF time: {e}")
        return None


def _offset(text) -> timedelta:
    """'+08:00' as a timedelta; the boat's offset when the photo has none."""
    try:
        sign = -1 if str(text)[0] == '-' else 1
        hours, minutes = str(text)[1:].split(':')
        return sign * timedelta(hours=int(hours), minutes=int(minutes))
    except Exception:
        return BOAT_OFFSET


def remove(image_path: Path):
    """Delete a photo's web copy, thumbnail and original."""
    stem = image_path.stem[:-4] if image_path.stem.endswith('_web') else image_path.stem
    for path in [image_path, thumb_path(image_path)] + list(image_path.parent.glob(stem + '.*')):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
