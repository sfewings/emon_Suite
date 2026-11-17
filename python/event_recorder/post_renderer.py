"""
Post renderer (FR-24): a post as a list of blocks, turned into WordPress block
markup by one function, for the preview on the Pi and the post on
enchantee.org alike.

Two kinds of block:

- Content blocks hold what the crew wrote or added: 'paragraph', 'photo',
  'more'.
- Auto blocks hold only a reference, and are drawn from the recording's
  current data every time: 'track_summary', 'crew_photos', 'log_lines',
  'photos', 'statistics', 'route_map', 'interactive_map', 'charts',
  'downloads'.

The preview and the publish differ only in the PostContext they render
against: image URLs on the Pi and no attachment ids for the one, WordPress
media URLs and ids for the other. Everything else is the same code, which is
what lets the preview be trusted to show the post.

The markup is core block markup, delimited (<!-- wp:paragraph --> and so on),
the same as the hand-written posts on enchantee.org carry, so a post opened in
the block editor opens as blocks rather than one Classic block. The two
exceptions are wp:html, around the statistics table, whose inline styles a
core table block would not keep, and around the folium maps, whose scripts
wpautop would otherwise mangle.
"""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# How a time is written in the post: seconds are as fine as a reader needs,
# and the database's microseconds only made the date line hard to read.
DISPLAY_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# The stylesheets an embedded map may bring into the page with it. Every
# rule in these is scoped to the map's own classes. Anything else folium
# links, Bootstrap above all, styles the elements of the page itself and
# cannot be let near a post.
MAP_STYLESHEETS = (
    'leaflet.css',
    'awesome-markers',
    'awesome.rotate',
    'fontawesome',
)

# The post as it was, block for block (FR-16 as it stood before FR-24). Kept
# so the post_layout setting can choose it.
LAYOUT_TRACK_LOG = [
    {'type': 'track_summary'},
    {'type': 'crew_photos'},
    {'type': 'statistics', 'heading': True},
    {'type': 'route_map'},
    {'type': 'more'},
    {'type': 'interactive_map'},
    {'type': 'charts'},
    {'type': 'downloads'},
]

# FR-25: the shape of the hand-written posts on enchantee.org, with the
# recorder's data below the break instead of in front of the story
LAYOUT_SHIP_LOG = [
    {'type': 'log_lines'},
    {'type': 'story'},
    {'type': 'photos'},
    {'type': 'route_map'},
    {'type': 'more'},
    {'type': 'statistics', 'heading': True},
    {'type': 'interactive_map'},
    {'type': 'charts'},
    {'type': 'downloads'},
]

LAYOUTS = {'track_log': LAYOUT_TRACK_LOG, 'ship_log': LAYOUT_SHIP_LOG}

# What a recording publishes as unless its draft or the post_layout setting
# says otherwise. The ship's log since FR-25 was approved (2026-10-09).
DEFAULT_LAYOUT = 'ship_log'


class PostContext:
    """
    What a post is drawn from. The publisher fills it after uploading; the
    preview fills it from files on the Pi.

    Media dicts carry: 'url', 'large_url' (the 1024 px size, or 'url'), 'id'
    (the WordPress attachment id, None in a preview), 'caption', 'path', and
    'image_type' ('plot' or 'user_upload').
    """

    def __init__(self, recording: Dict, media: List[Dict] = None,
                 statistics: Optional[Dict] = None, map_htmls: List[str] = None,
                 downloads: List[Dict] = None,
                 draft: Optional[Dict] = None):
        self.recording = recording
        self.media = media or []
        self.statistics = statistics
        self.map_htmls = map_htmls or []
        self.downloads = downloads or []
        self.draft = draft or {}

    @property
    def photos(self) -> List[Dict]:
        return [m for m in self.media if m.get('image_type') == 'user_upload']

    @property
    def plots(self) -> List[Dict]:
        return [m for m in self.media if m.get('image_type', 'plot') == 'plot']


def render(blocks: List[Dict], ctx: PostContext) -> str:
    """The post's content, as WordPress block markup."""
    # The primary route map is drawn by the route_map block, so the charts
    # block leaves it out rather than showing it twice
    ctx_plots = list(ctx.plots)
    route_map = pop_primary_route_map(ctx_plots)
    state = {'route_map': route_map, 'other_plots': ctx_plots}

    out = []
    for block in blocks:
        draw = _RENDERERS.get(block.get('type'))
        if draw is None:
            logger.warning(f"Unknown block type skipped: {block.get('type')}")
            continue
        out.append(draw(block, ctx, state))
    return ''.join(part for part in out if part)


# === Core block markup ===

def _paragraph(inner_html: str) -> str:
    return f'<!-- wp:paragraph -->\n<p>{inner_html}</p>\n<!-- /wp:paragraph -->\n\n'


def _heading(text: str, level: int = 2) -> str:
    attrs = '' if level == 2 else f' {{"level":{level}}}'
    return (f'<!-- wp:heading{attrs} -->\n'
            f'<h{level} class="wp-block-heading">{html.escape(text)}</h{level}>\n'
            f'<!-- /wp:heading -->\n\n')


def _image(media: Dict, caption: str = '', italic: bool = False,
           default_alt: str = '') -> str:
    """
    An image block. With a WordPress attachment id it is the block the
    editor writes itself, size 'large', so WordPress adds srcset and lazy
    loading and serves the 1024 px file rather than the full-size one.
    """
    safe_caption = html.escape(caption) if caption else ''
    alt = safe_caption or html.escape(default_alt)
    media_id = media.get('id')
    if media_id:
        url = media.get('large_url') or media.get('url', '')
        opening = f'<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->\n'
        figure = (f'<figure class="wp-block-image size-large">'
                  f'<img src="{html.escape(url)}" alt="{alt}" class="wp-image-{media_id}"/>')
    else:
        url = media.get('url', '')
        opening = '<!-- wp:image -->\n'
        figure = f'<figure class="wp-block-image"><img src="{html.escape(url)}" alt="{alt}"/>'
    if caption:
        body = f'<em>{safe_caption}</em>' if italic else safe_caption
        figure += f'<figcaption class="wp-element-caption">{body}</figcaption>'
    return opening + figure + '</figure>\n<!-- /wp:image -->\n\n'


def _html_block(markup: str) -> str:
    return f'<!-- wp:html -->\n{markup}\n<!-- /wp:html -->\n\n'


def _list(items_html: List[str]) -> str:
    items = ''.join(f'<!-- wp:list-item -->\n<li>{item}</li>\n<!-- /wp:list-item -->\n'
                    for item in items_html)
    return f'<!-- wp:list -->\n<ul class="wp-block-list">{items}</ul>\n<!-- /wp:list -->\n\n'


# === Blocks ===

def _track_summary(block, ctx, state):
    """The Track Summary heading, date and duration of today's post."""
    rec = ctx.recording
    start = local_time(rec.get('start_time'))
    out = _heading('Track Summary')
    out += _paragraph('<strong>Date:</strong> ' +
                      (start.strftime(DISPLAY_TIME_FORMAT) if start else 'N/A'))
    out += _paragraph('<strong>Duration:</strong> ' +
                      format_duration(rec.get('start_time'), rec.get('end_time')))
    if rec.get('description'):
        # Escaped: before FR-24 this went into the post as raw HTML
        out += _paragraph(html.escape(rec['description']))
    return out


def _crew_photos(block, ctx, state):
    """Every crew photo, italic by-line captions, no heading: today's post."""
    return ''.join(_image(m, m.get('caption', ''), italic=True, default_alt='Photo')
                   for m in ctx.photos)


def _photos(block, ctx, state):
    """
    Crew photos as the hand-written posts show them, captioned only when
    typed, in the order they were taken (FR-29). Undated photos keep their
    upload order, last.
    """
    items = [(_utc(m.get('taken_at')), i, m) for i, m in enumerate(ctx.photos)]
    items.sort(key=lambda item: (item[0] is None, item[0] or datetime.min, item[1]))
    return ''.join(_image(m, m.get('caption', ''), default_alt='Photo') for _, _, m in items)


def _utc(value) -> Optional[datetime]:
    """A stored or ISO 8601 time as naive UTC, for ordering; None if unreadable."""
    if not value:
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None
    if stamp.tzinfo:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return stamp


def _log_lines(block, ctx, state):
    """
    The lines at the top of every hand-written post: crew, time, wind, each
    its own paragraph (FR-25). The crew come from the draft; the time and the
    wind are the crew's where they typed them and the recording's otherwise
    (FR-26).
    """
    out = ''
    crew = ctx.draft.get('crew') or []
    if crew:
        out += _paragraph(html.escape(', '.join(crew)))
    # The crew's line where they typed one, else the recording's (FR-26)
    computed = ctx.draft.get('computed') or {}
    time_line = (block.get('time') or ctx.draft.get('time_line')
                 or computed.get('time_line') or log_time_line(ctx.recording))
    if time_line:
        out += _paragraph(html.escape(time_line))
    wind = block.get('wind') or ctx.draft.get('wind') or computed.get('wind')
    if wind:
        out += _paragraph(html.escape(wind))
    return out


def _story(block, ctx, state):
    """The draft's story, or the recording's description until there is one."""
    text = ctx.draft.get('story') or ctx.recording.get('description') or ''
    return ''.join(_paragraph(html.escape(p.strip()).replace('\n', '<br>'))
                   for p in re.split(r'\n\s*\n', text) if p.strip())


def _paragraph_block(block, ctx, state):
    return _paragraph(html.escape(block.get('text', '')).replace('\n', '<br>'))


def _photo_block(block, ctx, state):
    """One crew photo, placed by hand in the draft."""
    media = next((m for m in ctx.photos if m.get('path') == block.get('path')), None)
    if media is None:
        return ''
    return _image(media, block.get('caption', media.get('caption', '')), default_alt='Photo')


def _statistics(block, ctx, state):
    if not ctx.statistics:
        return ''
    out = ''
    # A race recording's legs, above the statistics they are the breakdown of (FR-32)
    race = race_table_html(ctx.statistics.get('race'))
    if race:
        out += (_heading('Race') if block.get('heading', True) else '') + _html_block(race)
    table = statistics_table_html(ctx.statistics)
    if table:
        out += (_heading('Statistics') if block.get('heading', True) else '') + _html_block(table)
    return out


def _route_map(block, ctx, state):
    """The drawn track, above the fold: the one picture that says what the day was."""
    route_map = state['route_map']
    if not route_map:
        return ''
    return _image(route_map, route_map.get('caption', ''))


def _more(block, ctx, state):
    # The red-shadow theme on enchantee.org renders the homepage with
    # the_content(), so without this break the listing carries the whole
    # post, map JS included, and the layout collapses under it. The inner tag
    # has no spaces: the_content() looks for <!--more-->, and <!-- more --> is
    # just a comment to it.
    return '<!-- wp:more -->\n<!--more-->\n<!-- /wp:more -->\n\n'


def _interactive_map(block, ctx, state):
    if not ctx.map_htmls:
        return ''
    out = _heading('Route Maps' if len(ctx.map_htmls) > 1 else 'Route Map')
    for html_path in ctx.map_htmls:
        embed = extract_folium_embed(html_path)
        if embed:
            # wp:html, or wpautop wraps the scripts in <p> and breaks them
            out += _html_block(embed)
    return out


def _charts(block, ctx, state):
    plots = state['other_plots']
    if not plots:
        return ''
    return _heading('Data Visualizations') + ''.join(
        _image(m, m.get('caption', '')) for m in plots)


def _downloads(block, ctx, state):
    if not ctx.downloads:
        return ''
    items = [f'<a href="{html.escape(d["url"])}" download>'
             f'{html.escape(d["label"])} ({html.escape(d["export_type"].upper())})</a>'
             for d in ctx.downloads]
    return _heading('Downloads') + _list(items)


_RENDERERS = {
    'track_summary': _track_summary,
    'crew_photos': _crew_photos,
    'photos': _photos,
    'log_lines': _log_lines,
    'story': _story,
    'paragraph': _paragraph_block,
    'photo': _photo_block,
    'statistics': _statistics,
    'route_map': _route_map,
    'more': _more,
    'interactive_map': _interactive_map,
    'charts': _charts,
    'downloads': _downloads,
}

BLOCK_TYPES = frozenset(_RENDERERS)


# === Helpers, moved here from wordpress_publisher.py ===

def local_time(value) -> Optional[datetime]:
    """
    Read a recorded timestamp and return it in the boat's timezone.

    Recordings are stored with datetime.utcnow(). Left alone, the post
    carried UTC throughout: an afternoon sail dated to that morning, and a
    WordPress date field that reads whatever it is given as site-local.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        stamp = value
    else:
        from dateutil import parser as _dateutil_parser
        try:
            stamp = _dateutil_parser.parse(str(value))
        except (ValueError, OverflowError, TypeError):
            return None

    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone().replace(tzinfo=None)


def format_duration(start_time, end_time) -> str:
    """Format duration between timestamps."""
    try:
        if not start_time or not end_time:
            return "N/A"

        from dateutil import parser
        start = parser.parse(str(start_time))
        end = parser.parse(str(end_time))

        duration = end - start

        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        seconds = duration.seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    except Exception as e:
        logger.warning(f"Failed to format duration: {e}")
        return "N/A"


def log_time_line(recording: Dict) -> str:
    """
    'H:MM-H:MM' in local time, the way the hand-written posts give it
    ("5:30-8:20"): twelve-hour, no am or pm, no leading zero.
    """
    def clock(stamp):
        return f"{stamp.hour % 12 or 12}:{stamp.minute:02d}"

    start = local_time(recording.get('start_time'))
    if not start:
        return ''
    end = local_time(recording.get('end_time'))
    return f"{clock(start)}-{clock(end)}" if end else clock(start)


# apply_template() was here, with PostContext.template and the branch in
# _track_summary() that used them. Nothing ever supplied a template: the event config's
# `wordpress.template` was never read, _publish_options() never set one, and the only
# other way in was an optional field on the publish API that no caller sends. The post
# is composed from the draft's blocks instead (FR-25). It also substituted only six
# placeholders, so the templates written in the configs, which name {distance},
# {max_speed} and {energy_used}, would have raised KeyError and published the template
# as literal text had anything reached it. Removed 12 Nov 2026.


def pop_primary_route_map(plots: List[Dict]) -> Optional[Dict]:
    """
    Remove the first route map from a list of plots and return it.

    Titles are 'Route Map' for a single GPS unit and 'Route Map 0',
    'Route Map 1' when the boat carries more than one; sorting picks the
    lowest, which is the primary unit. The remaining units' maps stay with
    the other charts.
    """
    def is_route_map(media: Dict) -> bool:
        caption = (media.get('caption') or '').strip().lower()
        stem = Path(media.get('path', '')).stem.lower()
        return caption.startswith('route map') or stem.startswith('route_map')

    candidates = [m for m in plots if is_route_map(m)]
    if not candidates:
        return None

    primary = min(candidates,
                  key=lambda m: (m.get('caption') or Path(m.get('path', '')).stem))
    plots.remove(primary)
    return primary


# Weather statistics, which read as false precision at two decimals
_ONE_DECIMAL = {'air_temperature', 'humidity', 'pressure'}


def statistics_table_html(statistics: Dict) -> str:
    """Render statistics dict as an HTML table, inline-styled as the posts have it."""
    ordered_keys = [
        'start_time', 'end_time', 'duration',
        'distance_km', 'max_speed', 'avg_speed',
        'total_energy_wh', 'avg_power_w', 'max_power_w',
        'battery_cycles',
        'air_temperature_min', 'air_temperature_mean', 'air_temperature_max',
        'humidity_min', 'humidity_mean', 'humidity_max',
        'pressure_min', 'pressure_mean', 'pressure_max',
        'message_count',
    ]
    label_map = {
        'start_time':        ('Start Time',        ''),
        'end_time':          ('End Time',          ''),
        'duration':          ('Duration',          ''),
        # Nautical miles, as the speeds beside it are knots and the
        # hand-written posts use knots (FR-26). Converted below.
        'distance_km':       ('Distance',          'nm'),
        # knots, not km/h: these come straight off gps/speed, which the
        # charts label knots too. Labelled km/h they disagreed with the
        # distance and duration beside them by a factor of 1.9.
        'max_speed':         ('Max Speed',         'knots'),
        'avg_speed':         ('Average Speed',     'knots'),
        'total_energy_wh':   ('Total Energy',      'Wh'),
        'avg_power_w':       ('Average Power',     'W'),
        'max_power_w':       ('Max Power',         'W'),
        # The pack's lifetime cycle count, a number rather than a chart of a
        # near-flat line.
        'battery_cycles':    ('Battery Cycles',    ''),
        # The weather over the sail, from the sensor in the anemometer at the
        # masthead. Min, mean and max rather than one number: a reader wants to
        # know it was 18 to 24 degrees, not that the average was 21.
        'air_temperature_min':  ('Air Temperature (min)',  '°C'),
        'air_temperature_mean': ('Air Temperature (mean)', '°C'),
        'air_temperature_max':  ('Air Temperature (max)',  '°C'),
        'humidity_min':         ('Humidity (min)',         '%'),
        'humidity_mean':        ('Humidity (mean)',        '%'),
        'humidity_max':         ('Humidity (max)',         '%'),
        'pressure_min':         ('Air Pressure (min)',     'hPa'),
        'pressure_mean':        ('Air Pressure (mean)',    'hPa'),
        'pressure_max':         ('Air Pressure (max)',     'hPa'),
        'message_count':     ('Messages Recorded', ''),
    }
    # 'race' is the leg table, drawn by race_table_html
    skip = {'duration_seconds', 'race'}

    def make_row(key, value):
        label, unit = label_map.get(key, (key.replace('_', ' ').title(), ''))
        if key == 'distance_km' and isinstance(value, (int, float)):
            value = float(value) / 1.852
        if key.rsplit('_', 1)[0] in _ONE_DECIMAL and isinstance(value, (int, float)):
            # A tenth of a degree or a millibar is as fine as these sensors read;
            # '62.37 %' claims a precision the humidity sensor does not have.
            formatted = f"{value:.1f}"
        elif key == 'battery_cycles' and isinstance(value, (int, float)):
            # A whole number of cycles; '34.00' reads as a measurement it is not.
            formatted = f"{value:.0f}"
        elif isinstance(value, float):
            formatted = f"{value:.2f}"
        else:
            formatted = html.escape(str(value))
        if unit:
            formatted = f"{formatted} {html.escape(unit)}"
        return (
            f'  <tr><th style="text-align:left;padding:6px 12px;'
            f'background:#f2f2f2;border:1px solid #ddd;">'
            f'{html.escape(label)}</th>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;">'
            f'{formatted}</td></tr>\n'
        )

    rows = []
    seen = set()
    for key in ordered_keys:
        if key in statistics and key not in skip:
            rows.append(make_row(key, statistics[key]))
            seen.add(key)
    for key, value in statistics.items():
        if key not in seen and key not in skip:
            rows.append(make_row(key, value))

    if not rows:
        return ''

    return ('<table style="border-collapse:collapse;width:100%;max-width:480px;">\n'
            + ''.join(rows) + '</table>')


_CELL = 'padding:4px 8px;border:1px solid #ddd;text-align:right;white-space:nowrap;'
_HEAD = 'padding:4px 8px;border:1px solid #ddd;background:#f2f2f2;text-align:center;'


def _nm_km(metres) -> str:
    """Both units, as the owner asked: nautical miles for the crew, km for everyone else."""
    if not isinstance(metres, (int, float)):
        return ''
    return f"{metres / 1852.0:.2f} nm<br>{metres / 1000.0:.2f} km"


def _hms(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return ''
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _num(value, decimals=1, unit='') -> str:
    if not isinstance(value, (int, float)):
        return ''
    return f"{value:.{decimals}f}{unit}"


def race_table_html(race: Optional[Dict]) -> str:
    """A race recording's legs as an HTML table, one row per leg and totals (FR-32).

    Wind directions and angles are whole degrees; speeds one decimal, as the
    instruments read. Each AWA is the mean angle off the bow on that tack, so a leg
    sailed on one tack has the other blank.
    """
    if not isinstance(race, dict) or not race.get('legs'):
        return ''

    lines = []
    course = race.get('course_name') or race.get('course')
    if course:
        lines.append(f"Course: {html.escape(str(course))}")
    if race.get('gun_local'):
        lines.append(f"Start: {html.escape(race['gun_local'])}")
    if race.get('finish_local'):
        lines.append(f"Finish: {html.escape(race['finish_local'])}")
    elif not race.get('finished'):
        lines.append('Not finished')
    start = race.get('start') or {}
    if isinstance(start.get('distance_to_line_m'), (int, float)):
        where = f"{start['distance_to_line_m']:.0f} m"
        if start.get('side'):
            where += f" {html.escape(start['side'])}"
        lines.append(f"At the gun: {where} the line" if start.get('side')
                     else f"At the gun: {where} from the line")

    headers = ['Leg', 'Mark', 'Leg length', 'Point of sail', 'Distance sailed',
               'Duration', 'Avg speed (kn)', 'TWD (°)', 'TWS min (kn)', 'TWS mean (kn)',
               'TWS max (kn)', 'AWA port (°)', 'AWA stbd (°)']

    def row(cells, bold=False):
        style = _CELL + ('font-weight:bold;background:#f8f8f8;' if bold else '')
        return '  <tr>' + ''.join(f'<td style="{style}">{c}</td>' for c in cells) + '</tr>\n'

    def wind_cells(r):
        return [_num(r.get('avg_speed_kn')), _num(r.get('twd'), 0),
                _num(r.get('tws_min')), _num(r.get('tws_mean')), _num(r.get('tws_max')),
                _num(r.get('awa_port'), 0), _num(r.get('awa_starboard'), 0)]

    body = ''
    for leg in race['legs']:
        name = html.escape(str(leg.get('name') or ''))
        if leg.get('unfinished'):
            name += ' (unfinished)'
        body += row([str(leg.get('leg', '')), name, _nm_km(leg.get('length_m')),
                     html.escape(leg.get('point_of_sail') or ''),
                     _nm_km(leg.get('distance_m')), _hms(leg.get('duration_s'))]
                    + wind_cells(leg))
    total = race.get('total') or {}
    body += row(['', 'Total', _nm_km(total.get('length_m')), '',
                 _nm_km(total.get('distance_m')), _hms(total.get('duration_s'))]
                + wind_cells(total), bold=True)

    head = '  <tr>' + ''.join(f'<th style="{_HEAD}">{html.escape(h)}</th>'
                              for h in headers) + '</tr>\n'
    summary = (f'<p>{" · ".join(lines)}</p>\n' if lines else '')
    # Thirteen columns do not fit a phone; the table scrolls inside its own box
    # rather than widening the page
    return (summary + '<div style="overflow-x:auto;">\n'
            '<table style="border-collapse:collapse;font-size:0.85em;">\n'
            + head + body + '</table>\n</div>')


def extract_folium_embed(html_path: str, height: int = 500) -> str:
    """
    Extract an embeddable HTML snippet from a folium-generated map file.

    Folium saves a full standalone HTML page. This pulls out the CDN
    stylesheets the map needs (and no others), the CDN scripts, the map <div>
    at a fixed height, and the Leaflet initialisation <script> that folium
    places after </body>. Admin users with the unfiltered_html capability can
    save <script> tags through the REST API, so the map renders in the post.
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        parts = []

        # Only the map's own stylesheets. folium also links the whole
        # Bootstrap framework and Bootstrap 3's glyphicons, and both carry a
        # CSS reset: html{font-size:62.5%}, body{margin:0} and rules for
        # figure and img. Copied into a post they restyle the page around the
        # map, which is what pushed the blog off centre, changed its type size
        # and dropped the banner.
        for m in re.finditer(
            r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>',
            content, re.IGNORECASE
        ):
            href_m = re.search(r'href=["\']([^"\']+)["\']', m.group(0))
            href = href_m.group(1) if href_m else ''
            if any(part in href for part in MAP_STYLESHEETS):
                parts.append(m.group(0))
            else:
                logger.debug(f"Skipping page-wide stylesheet in map embed: {href}")

        seen_srcs = set()
        for m in re.finditer(
            r'<script\b[^>]*\bsrc="([^"]+)"[^>]*>\s*</script>',
            content, re.IGNORECASE
        ):
            src = m.group(1)
            if src not in seen_srcs:
                seen_srcs.add(src)
                parts.append(f'<script src="{src}"></script>')

        id_m = re.search(
            r'<div\b[^>]*\bclass="folium-map"[^>]*\bid="([^"]+)"',
            content, re.IGNORECASE
        )
        if not id_m:
            logger.warning(f"Could not find folium map div in {html_path}")
            return ''
        map_id = id_m.group(1)

        parts.append(
            f'<style>'
            f'#{map_id}{{position:relative;width:100%;height:{height}px;}}'
            f'.leaflet-container{{font-size:1rem;}}'
            f'</style>'
        )
        # Leaflet initialisation flags (needed by awesome-markers plugin)
        parts.append('<script>L_NO_TOUCH=false;L_DISABLE_3D=false;</script>')
        parts.append(f'<div class="folium-map" id="{map_id}"></div>')

        body_end = content.lower().rfind('</body>')
        if body_end != -1:
            tail = content[body_end + len('</body>'):]
            script_m = re.search(r'<script\b[^>]*>(.*?)</script>',
                                 tail, re.DOTALL | re.IGNORECASE)
            if script_m:
                parts.append(f'<script>{script_m.group(1)}</script>')

        logger.info(f"Extracted folium embed from {Path(html_path).name}")
        return '\n'.join(parts)

    except Exception as e:
        logger.warning(f"Could not extract folium embed from {html_path}: {e}")
        return ''
