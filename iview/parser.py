from . import config
from xml.etree.cElementTree import XML
import json
from datetime import datetime
import re
from .utils import xml_text_elements
import sys
from collections import Mapping
import unicodedata
from warnings import warn
from urllib.parse import urlsplit

def parse_config(soup):
    """There are lots of goodies in the config we get back from the ABC.
    In particular, it gives us the URLs of all the other XML data we
    need.
    """

    xml = XML(soup)
    params = dict()
    for param in xml.iter('param'):
        params.setdefault(param.get('name'), param.get('value'))

    # should look like "rtmp://cp53909.edgefcs.net/ondemand"
    # Looks like the ABC don't always include this field.
    # If not included, that's okay -- ABC usually gives us the server in the auth result as well.
    rtmp_url = params['server_streaming']
    categories_url = params['categories']

    params.update({
        'rtmp_url'  : rtmp_url,
        'auth_url'  : params['auth'],
        'api_url' : params['api'],
        'categories_url' : categories_url,
        'captions_url' : params['captions'],
    })
    return params

def parse_auth(soup, iview_config):
    """There are lots of goodies in the auth handshake we get back,
    including the streaming server URL, auth tokens,
    and whether the connection is unmetered.
    """

    xml = XML(soup)
    xmlns = "{http://www.abc.net.au/iView/Services/iViewHandshaker}"
    auth = xml_text_elements(xml, xmlns)

    if config.override_host == 'default':
        auth['host'] = None
        auth['path'] = config.akamai_playpath_prefix
    elif config.override_host:
        auth.update(config.stream_hosts[config.override_host])
        auth['host'] = config.override_host

    if config.override_host == 'default' or not auth.get('server'):
        # We are a bland generic ISP using Akamai, or we are iiNet.
        auth['server'] = iview_config['server_streaming']
        auth['bwtest'] = iview_config['server_fallback']
    
    playpath_prefix = auth.get('path')
    if playpath_prefix is None:
        # at time of writing, either 'Akamai' (usually metered) or 'Hostworks' (usually unmetered)
        stream_host = auth['host']
        if stream_host == 'Akamai':
            playpath_prefix = config.akamai_playpath_prefix
        else:
            playpath_prefix = ''

    # should look like "rtmp://203.18.195.10/ondemand"
    rtmp_url = auth['server']

    auth.update({
        'rtmp_url'        : rtmp_url,
        'playpath_prefix' : playpath_prefix,
        'free'            : (auth["free"] == "yes")
    })
    return auth

def parse_json_feed(soup):
    if not soup:
        raise ValueError('Empty feed API response')
    index_json = json.loads(soup.decode('utf-8'))
    
    series = dict()  # Programme series (seasons) by series id.
    for item in index_json:
        this_series = api_attributes(item, (
            ('id', 'seriesId'),
            ('title', 'seriesTitle'),
            ('series', 'seriesNumber'),
        ))
        existing = series.get(this_series['id'])
        if existing is None:
            this_series['items'] = list()
            series[this_series['id']] = this_series
        else:
            if this_series['title'] != existing['title']:
                msg = 'Series {id} title also {title!r}'
                warn(msg.format_map(this_series))
            existing_number = existing.get('series')
            if existing_number not in {None, this_series.get('series')}:
                warn('Series {} number changes'.format(this_series['id']))
                del existing['series']
            this_series = existing
        
        for optional_key in ('description', 'thumb', 'linkURL'):
            item.setdefault(optional_key, '')
        episode = api_attributes(item, (
            ('id', 'episodeId'),
            ('title', 'title'),
            ('description', 'description'),
            ('category', 'category'),
            ('date', 'pubDate'),
            ('expires', 'expireDate'),
            ('size', 'fileSize'),
            ('duration', 'duration'),
            ('home', 'linkURL'),
            ('url', 'videoAsset'),
            ('rating', 'rating'),
            ('warning', 'warning'),
            ('thumb', 'thumbnail'),
            ('series', 'seriesNumber'),
            ('episode', 'episodeNumber'),
        ))
        
        split = urlsplit(episode['url'])
        prefix = '/playback/_definst_/'
        if split.path.startswith(prefix):
            episode['url'] = split.path[len(prefix):]
        else:
            warn('Unexpected videoAsset ' + repr(episode['url']))
        
        episode['livestream'] = ''
        parse_field(episode, 'duration', int)
        parse_field(episode, 'size', lambda size: float(size) * 1e6)
        for field in ('date', 'expires'):
            parse_field(episode, field, parse_date)
        
        title = episode.get('title')
        if title:
            # Seen newline character in a title. Perhaps it is meant to be
            # treated like HTML and collapsed into a single space.
            title = title.translate(BadCharMap())
            episode['title'] = ' '.join(title.split())
        else:
            episode['title'] = this_series['title']
        
        this_series['items'].append(episode)
    
    def get_title(series):
        """Alphabetically sort by series title"""
        return casefold(series['title'])
    return sorted(series.values(), key=get_title)

def parse_categories(soup):
    xml = XML(soup)

    # Get all the top level categories
    return category_node(xml)

def category_node(xml):
    categories_list = []

    """
    <category id="pre-school" genre="true">
        <name>ABC 4 Kids</name>
    </category>
    """

    # Get all the top level categories
    
    for cat in xml.iterfind('category'):
        item = dict(cat.items())
        
        genre = item.get("genre")
        if genre is not None:
            item["genre"] = genre == "true"
        
        item.update(xml_text_elements(cat))
        item['children'] = category_node(cat)
        
        categories_list.append(item);

    return categories_list

def category_ids(categories):
    ids = dict()
    for cat in categories:
        ids[cat['id']] = cat
        ids.update(category_ids(cat['children']))
    return ids

def parse_date(date):
    if date in {'0000-00-00 00:00:00', '0000-00-00'}:
        return None
    
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(date, fmt)
        except ValueError:
            continue
    else:
        raise ValueError("Unknown format {!r}".format(date))

def parse_field(result, key, parser):
    value = result.get(key)
    if not value:
        return
    try:
        result[key] = parser(value)
    except ValueError as err:
        msg = 'Removing {!r} field: {}'.format(key, err)
        print(msg, file=sys.stderr)
        del result[key]

def api_attributes(input, attributes):
    result = dict()
    for (key, code) in attributes:
        value = input.get(code)
        # Some queries return a limited set of fields, for example
        # the thumbnail is missing from "seriesIndex"
        if value is not None:
            result[key] = value
    
    # HACK: replace &amp; with & because HTML entities don't make
    # the slightest bit of sense inside a JSON structure.
    for key in ('title', 'description'):
        value = result.get(key)
        if value is not None:
            result[key] = value.replace('&amp;', '&')
    
    return result

class BadCharMap(Mapping):
    """Maps unwanted control characters to spaces"""
    
    def __iter__(self):
        return iter(range(len(self)))
    def __len__(self):
        return sys.maxunicode + 1
    
    def __getitem__(self, cp):
        category = unicodedata.category(chr(cp))
        if category == "Cn":
            # Remove the defined "non-characters", but leave other unassigned
            # characters as-is
            if 0xFDD0 <= cp < 0xFDF0 or cp & 0xFFFE == 0xFFFE:
                return " "
        elif (category.startswith("C") and category != "Cf" or
                category in {"Zl", "Zp"}):
            return " "
        raise KeyError("Good character")

def parse_highlights(xml):

    soup = XML(xml)

    highlightList = []

    for series in soup.iterfind('series'):
        tempSeries = dict(series.items())
        tempSeries.update(xml_text_elements(series))
        highlightList.append(tempSeries)

    return highlightList

def series_categories(categories, series):
    """Yields the categories of a series based on its "keywords" field
    
    The keywords field contains category identifiers separated by spaces,
    but also contains other items clearly not intended to be separated
    (e.g. "bananas in pyjamas")."""
    
    for id in series['keywords'].split():
        category = categories.get(id)
        if category is not None:
            yield category

def parse_captions(soup):
    """Converts custom iView captions into SRT format, usable in most
    decent media players.
    """
    
    # Horrible hack to escape literal ampersands, which have been seen in
    # some captions XML. Inspired by
    # http://stackoverflow.com/questions/6088760/fix-invalid-xml-with-ampersands-in-python
    if b"<![CDATA[" not in soup:  # Not seen, but be future proof
        soup = re.sub(b"&(?![#\w]+;)", b"&amp;", soup)
    
    xml = XML(soup)

    output = ''

    i = 1
    for title in xml.iter('title'):
        start = title.get('start')
        (start, startfract) = start.rsplit(':', 1)
        end = title.get('end')
        (end, endfract) = end.rsplit(':', 1)
        output = output + '{}\n'.format(i)
        output = output + '{},{:0<3.3} --> {},{:0<3.3}\n'.format(start, startfract, end, endfract)
        output = output + title.text.replace('|','\n') + '\n\n'
        i += 1

    return output

# casefold() is new in Python 3.3
casefold = getattr(str, "casefold", str.lower)
