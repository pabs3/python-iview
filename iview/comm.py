from __future__ import print_function

import os
import sys
from . import config
from . import parser
import gzip
from io import BytesIO
# "urllib_request" is imported at end


cache = False

iview_config = None
channels = None

def fetch_url(url):
	"""	Simple function that fetches a URL using urllib.
		An exception is raised if an error (e.g. 404) occurs.
	"""
	http = urllib_request.urlopen(
		urllib_request.Request(url, None, {
			'User-Agent' : config.user_agent,
		 	'Accept-Encoding' : 'gzip'
		 })
	)
	headers = http.info()
	if 'content-encoding' in headers and headers['content-encoding'] == 'gzip':
		data = BytesIO(http.read())
		return gzip.GzipFile(fileobj=data).read()
	else:
		return http.read()

def maybe_fetch(url):
	"""	Only fetches a URL if it is not in the cache/ directory.
		In practice, this is really bad, and only useful for saving
		bandwidth when debugging. For one, it doesn't respect
		HTTP's wishes. Also, iView, by its very nature, changes daily.
	"""

	if not cache:
		return fetch_url(url)

	if not os.path.isdir('cache'):
		os.mkdir('cache')

	filename = os.path.join('cache', url.split('/')[-1])

	if os.path.isfile(filename):
		f = open(filename, 'rb')
		data = f.read()
		f.close()
	else:
		data = fetch_url(url)
		f = open(filename, 'wb')
		f.write(data)
		f.flush()
		os.fsync(f.fileno())
		f.close()

	return data

def get_config():
	"""	This function fetches the iView "config". Among other things,
		it tells us an always-metered "fallback" RTMP server, and points
		us to many of iView's other XML files.
	"""
	global iview_config

	iview_config = parser.parse_config(maybe_fetch(config.config_url))

def get_auth():
	""" This function performs an authentication handshake with iView.
		Among other things, it tells us if the connection is unmetered,
		and gives us a one-time token we need to use to speak RTSP with
		ABC's servers, and tells us what the RTMP URL is.
	"""
	auth = fetch_url(iview_config['auth_url'])
	return parser.parse_auth(auth, iview_config)

def get_index():
	"""	This function pulls in the index, which contains the TV series
		that are available to us. The index is possibly encrypted, so we
		must decrypt it here before passing it to the parser.
	"""

	index_data = maybe_fetch(iview_config['api_url'] + 'seriesIndex')

	return parser.parse_index(index_data)

def get_series_items(series_id, get_meta=False):
	"""	This function fetches the series detail page for the selected series,
		which contain the items (i.e. the actual episodes).
	"""

	series_json = maybe_fetch(iview_config['api_url'] + 'series=%s' % series_id)

	# Bad series number returns empty json string, ignore it.
	if series_json == b'[]':
		print('no results for series id %s, skipping' % series_id, file=sys.stderr)
		return []
	
	return parser.parse_series_items(series_json, get_meta)

def get_captions(url):
	"""	This function takes a program name (e.g. news/730report_100803) and
		fetches the corresponding captions file. It then passes it to
		parse_subtitle(), which converts it to SRT format.
	"""

	captions_url = iview_config['captions_url'] + '%s.xml'

	xml = maybe_fetch(captions_url % url)
	return parser.parse_captions(xml)

def configure_socks_proxy():
	"""	Import the modules necessary to support usage of a SOCKS proxy
		and configure it using the current settings in iview.config
		NOTE: It would be safe to call this function multiple times
		from, say, a GTK settings dialog
	"""
	try:
		import socks
		import socket
		socket.socket = socks.socksocket
	except:
		print("The Python SOCKS client module is required for proxy support.")
		print("On Debian/Ubuntu this is provided by the python-socksipy package.")
		sys.exit(3)

	socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, config.socks_proxy_host, config.socks_proxy_port)

if config.socks_proxy_host is not None:
	configure_socks_proxy()

# must be done after the (optional) SOCKS proxy is configured
try:
	# Try Python 2 version first, to avoid incorrectly importing Python
	# 2's original "urllib"
	import urllib2 as urllib_request
	from urllib2 import HTTPError
except ImportError:
	# Python 3 version
	from urllib import request as urllib_request
	from urllib.error import HTTPError
