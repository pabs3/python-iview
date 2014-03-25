Python command-line and GTK+ interface to ABC iView

Copyright © 2009–2010 by Jeremy Visser <jeremy@visser.name>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Requirements
============

* Python 3.2+, <http://www.python.org/>

For the GUI:

* Py G Object, <https://live.gnome.org/PyGObject>.
  Debian and Ubuntu package: python3-gi.
* GTK 3, <http://www.gtk.org/>, including the G Object introspection bindings

Optional dependencies:

* For the live News 24 stream, or to use the RTMP streaming host:
  rtmpdump, <https://rtmpdump.mplayerhq.hu/>
* To use a SOCKS proxy: Py Socks, <https://github.com/Anorov/PySocks>,
  or socksipy, <https://code.google.com/p/socksipy-branch/>

Installation
============

1. Make sure Python is installed and working.
2. Either run ./iview-cli or ./iview-gtk.

Usage
=====

Some usage examples are provided for your perusal.

This is a purely informational command. It verifies that handshaking is
working correctly, and shows which streaming host is used.

	$ ./iview-cli --print-auth
	iView auth data:
	    Streaming Host: Akamai
	    RTMP Token: [...]
	    HDS Token: [...]
	    Server URL: http://iviewmetered-vh.akamaihd.net/z/
	    Playpath Prefix: playback/_definst_/
	    Unmetered: False

This can be used to list the iView programmes and
find a programme’s file name:

	$ ./iview-cli --programme
	7.30:
	    7.30 Episode 193 26/11/2013	(news/730s_Tx_2611.mp4)
	    7.30 25/11/2013	(news/730s_Tx_2511.mp4)
	    7.30 20/11/2013	(news/730s_Tx_2011.mp4)
	[...]

To actually download the programme, use something like the following:

	$ ./iview-cli --download news/730s_Tx_2611.mp4

Hopefully that will download an .flv file into your current directory,
appropriately named. Downloaded files always use the FLV container format,
despite any “.mp4” suffix in the original name.

RTMP
===

Iview now seems to use the HDS protocol for most programmes,
although it used to use the RTMP protocol.
However, RTMP still seems to be used for the News 24 live stream,
and the on-demand programmes still seem to be available
from the old RTMP host.
The RTMP downloader supports resuming interrupted files,
even though the HDS downloader currently does not.

To use RTMP, install _rtmpdump_.
If building from source,
copy _rtmpdump_ to somewhere within your $PATH (e.g. /usr/local/bin).
The RTMP host may be forced with the “iview-cli --host AkamaiRTMP” option.

Hacking
=======

Uh...good luck.

There are a few variables that can be edited in the “config.py” file.

:wq
