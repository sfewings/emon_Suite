# Fix: Post Content Breaking Theme Layout on Homepage

## Problem

When `publish_recording` creates a post with a folium map embed, the entire
post content (577KB+) is displayed on the homepage, breaking the theme layout.

The root cause: the post content has **no `<!-- more -->` tag**, so WordPress
outputs the full content (including hundreds of thousands of GPS coordinates
in JavaScript arrays) on the homepage listing instead of showing a summary
with a "Read more" link.

The old "red-shadow" theme uses `the_content()` on the homepage, which respects
the `<!-- more -->` tag to split content. Without it, everything is shown.

## Solution

Insert a `<!-- more -->` tag in the `_build_content` method of
`wordpress_publisher.py`, after the summary/statistics section and before the
map/images/downloads sections.

### Change Required in `wordpress_publisher.py`

In the `_build_content` method, after the statistics table and before the map
embed section, add:

```python
# Insert "more" tag so homepage shows summary only, not the full map/data
content += "\n<!-- more -->\n"
```

#### Where to insert it

Find this section in `_build_content`:

```python
        # Statistics table (HTML, not image)
        if statistics:
            content += self._build_statistics_table_html(statistics)

        # Interactive route map(s) — embedded folium HTML
```

Change it to:

```python
        # Statistics table (HTML, not image)
        if statistics:
            content += self._build_statistics_table_html(statistics)

        # Insert "more" tag so homepage shows summary only, not the full
        # map data and images. Without this, themes that use the_content()
        # on the homepage will render the entire 500KB+ post including raw
        # JavaScript GPS coordinate arrays, breaking the page layout.
        content += "\n<!-- more -->\n"

        # Interactive route map(s) — embedded folium HTML
```

### Why This Works

| Location | What shows |
|---|---|
| Homepage (listing) | Summary, statistics table, then "Read more..." link |
| Single post page | Everything: summary, statistics, map, images, downloads |

The `<!-- more -->` tag is WordPress's standard mechanism for splitting post
content between excerpt and full view. It's invisible on the single post page
but creates a break point on archive/homepage listings.

### Testing

After making the change, publish a test recording and verify:

1. **Homepage** — The post shows only the summary and statistics, with a
   "Read more" or "Continue reading" link. No raw JavaScript or GPS data
   visible.

2. **Single post page** — The full content renders correctly, including the
   folium map, images, and download links.

3. **Page size** — The homepage HTML should be dramatically smaller (the
   577KB content is replaced by a few KB of summary + a link).

### Alternative: Use Excerpts

If you prefer not to modify `_build_content`, you could instead set the
`post_excerpt` field when creating the post. However, not all themes respect
excerpts — the "red-shadow" theme on enchantee.org uses `the_content()`, so
the `<!-- more -->` tag is the reliable fix.

### Note on Folium Map Size

The folium map embed can be very large because it includes all GPS coordinates
as inline JavaScript arrays. For a 2-hour recording with 200,000+ messages,
the map data alone can be 500KB+. The `<!-- more -->` tag prevents this from
loading on the homepage, which also improves page load performance.

If you want to reduce the map size further, consider:
- Downsampling the GPS polyline (e.g., every 10th point instead of every point)
- Using a simpler map style
- Hosting the map data as a separate JSON file loaded via fetch()
