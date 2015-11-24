import os
import urllib.request
import sys
import socket
from . import config
from . import parser
import gzip
from urllib.parse import urljoin, urlsplit
from urllib.parse import urlencode
from .utils import http_get
from base64 import b64encode

iview_config = None

def fetch_url(url, types=None, headers=()):
    """Simple function that fetches a URL using urllib.
    An exception is raised if an error (e.g. 404) occurs.
    """
    url = urljoin(config.base_url, url)
    all_headers = dict(iview_config['headers'])
    all_headers.update(headers)
    
    # Not using plain urlopen() because the combination of
    # urlopen()'s "Connection: close" header and
    # a "gzip" encoded response
    # sometimes seems to cause the server to truncate the HTTP response
    from .utils import PersistentConnectionHandler
    with PersistentConnectionHandler(timeout=30) as connection:
        session = urllib.request.build_opener(connection)
        try:
            with http_get(session, url, types, headers=all_headers) as http:
                headers = http.info()
                if headers.get('content-encoding') == 'gzip':
                    return gzip.GzipFile(fileobj=http).read()
                else:
                    return http.read()
        except socket.timeout as error:
            raise Error("Timeout accessing {!r}".format(url)) from error

def maybe_fetch(url, type=None, headers=()):
    """Only fetches a URL if it is not in the cache directory.
    In practice, this is really bad, and only useful for saving
    bandwidth when debugging. For one, it doesn't respect
    HTTP's wishes. Also, iView, by its very nature, changes daily.
    """

    if not config.cache:
        return fetch_url(url, type, headers=headers)

    if not os.path.isdir(config.cache):
        os.mkdir(config.cache)

    filename = os.path.join(config.cache, url.rsplit('/', 1)[-1])

    if os.path.isfile(filename):
        with open(filename, 'rb') as f:
            data = f.read()
    else:
        data = fetch_url(url, type, headers=headers)
        with open(filename, 'wb') as f:
            f.write(data)

    return data

def get_config(headers=()):
    """This function fetches the iView "config". Among other things,
    it tells us an always-metered "fallback" RTMP server, and points
    us to many of iView's other XML files.
    """
    global iview_config

    headers = dict(headers)
    try:
        headers['User-Agent'] = headers['User-Agent'] + ' '
    except LookupError:
        headers['User-Agent'] = ''
    headers['User-Agent'] += config.user_agent
    headers['Accept-Encoding'] = 'gzip'
    iview_config = dict(headers=headers)
    
    xml = maybe_fetch(config.config_url, ("application/xml", "text/xml"))
    parsed = parser.parse_config(xml)
    iview_config.update(parsed)

def get_auth():
    """This function performs an authentication handshake with iView.
    Among other things, it tells us if the connection is unmetered,
    and gives us a one-time token we need to use to speak RTSP with
    ABC's servers, and tells us what the RTMP URL is.
    """
    auth = iview_config['auth_url']
    if config.ip:
        query = urlsplit(auth).query
        query = query and query + "&"
        query += urlencode((("ip", config.ip),))
        auth = urljoin(auth, "?" + query)
    auth = fetch_url(auth, ("application/xml", "text/xml"))
    return parser.parse_auth(auth, iview_config)

def get_categories():
    """Returns the list of categories
    """
    url = iview_config['categories_url']
    category_data = maybe_fetch(url, ("application/xml", "text/xml"))
    categories = parser.parse_categories(category_data)
    return categories

def get_index():
    """This function pulls in the index, which contains the TV series
    that are available to us. Returns a list of "dict" objects,
    one for each series.
    """
    return get_keyword('index')

def get_series_items(series_id, get_meta=False):
    """This function fetches the series detail page for the selected series,
    which contain the items (i.e. the actual episodes). By
    default, returns a list of "dict" objects, one for each
    episode. If "get_meta" is set, returns a tuple with the first
    element being the list of episodes, and the second element a
    "dict" object of series infomation.
    """

    series = series_api('series', series_id)

    for meta in series:
        if meta['id'] == series_id:
            break
    else:
        # Bad series number used to return an empty JSON string, so ignore it.
        print('no results for series id {}, skipping'.format(series_id), file=sys.stderr)
        meta = {'items': []}
    
    items = meta['items']
    if get_meta:
        return (items, meta)
    else:
        return items

def get_keyword(keyword):
    return series_api('keyword', keyword)

def series_api(key, value=""):
    query = urlencode(((key, value),))
    url = 'https://tviview.abc.net.au/iview/feed/panasonic/?' + query
    type = "application/json"
    credentials = b64encode(b"feedtest:abc123")
    authorization = ('Authorization', b'Basic ' + credentials)
    index_data = maybe_fetch(url, (type,), headers=(authorization,))
    return parser.parse_json_feed(index_data)

def get_highlights():
    # Reported as Content-Type: text/html
    highlightXML = maybe_fetch(iview_config['highlights'])
    return parser.parse_highlights(highlightXML)

def get_captions(url):
    """This function takes a program name with the suffix stripped
    (e.g. _video/news_730s_Tx_1506_650000) and
    fetches the corresponding captions file. It then passes it to
    parse_subtitle(), which converts it to SRT format.
    """
    if url.startswith('_video/'):
        # Convert new URLs like the above example to "news_730s_tx_1506"
        url = url.split('/', 1)[-1].rsplit('_', 1)[0].lower()
    captions_url = urljoin('http://iview.abc.net.au/cc/', url + '.xml')

    TYPES = ("text/xml", "application/xml")
    xml = maybe_fetch(captions_url, TYPES)
    return parser.parse_captions(xml)

def configure_socks_proxy():
    """Import the modules necessary to support usage of a SOCKS proxy
    and configure it using the current settings in iview.config
    NOTE: It would be safe to call this function multiple times
    from, say, a GTK settings dialog
    """
    try:
        import socks
        import socket
        socket.socket = socks.socksocket
    except:
        sys.excepthook(*sys.exc_info())
        print("The Python SOCKS client module is required for proxy support.", file=sys.stderr)
        sys.exit(3)

    socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, config.socks_proxy_host, config.socks_proxy_port)

class Error(EnvironmentError):
    pass

if config.socks_proxy_host is not None:
    configure_socks_proxy()
