Python iView
============

[![Join the chat at https://gitter.im/sramsay64/python-iview](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/sramsay64/python-iview?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

Legal
=====

I am not a lawyer, This is not legal advice, This is merely a simplification of some information, Contact a lawyer for legal advice.  

This project is a community owned and run project. The copyright is owned by everyone and the GLP license legally means that everybody is entitled to use and share this software freely and without any restriction as long as it isn't sold and you tell people that it is under a GLP3 license. **However** this _only_ applies to the software itself, **not** anything that you download _using_ the software. Python-iView is to iView what a [VCR](https://en.wikipedia.org/wiki/Videocassette_recorder)(or [PVR](https://en.wikipedia.org/wiki/Digital_video_recorder)) is to live TV. Make sure that you only use this program in accordance with the law.

Quick start guide
=================

1. Download and install Python from [here](https://www.python.org/ftp/python/3.5.0/python-3.5.0.exe)
2. Download and extract [this zip file](https://github.com/sramsay64/python-iview/archive/master.zip) ([help](http://www.wikihow.com/Extract-Files))
3. Double click on `iview-tk.py`
4. Select a program from the left pane
5. Select an episode from the middle pane
6. Click download button and the right pane will show you the progress of the download
7. Go to the iView folder inside your videos folder

Email scott.ramsay64@gmail.com for help.

Licence
=======

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

For the old GUI (iview-gtk):

* Py G Object, <https://live.gnome.org/PyGObject>.
  Debian and Ubuntu package: python3-gi.
* GTK 3, <http://www.gtk.org/>, including the G Object introspection bindings

For the new GUI (iview-tk):

* Tkinter
	* Windows and Mac OS X: installed by default
	* Debian: `sudo apt-get install python3-tk`

Optional dependencies:

* For the live News 24 stream, or to use the RTMP streaming host:
  rtmpdump, <https://rtmpdump.mplayerhq.hu/>
* To use a SOCKS proxy: Py Socks, <https://github.com/Anorov/PySocks>,
  or socksipy, <https://code.google.com/p/socksipy-branch/>

Installation
============

## Windows

Make sure Python is installed and working. If you want to use the old GUI in windows you will

## Mac OS X

Make sure Python is installed and working.

## Linux

Install `python3` and `python3-tk`

For the new GUI:
*  run `python3 -c 'import tkinter'` to make sure that it all works.

Usage
=====

Either run `./iview-cli` or `./iview-gtk`

Old CLI (./iview-cli)
---------------------

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

Old GUI (./iview-gtk)
---------------------

`./iview-gtk`

New CLI (./iview-ng)
--------------------

Start with `./iview-ng`

### Basic Usage:

1. Find a show by searching with the find command  <br>
	`iView $ find <name of show>`  <br>
2. The epesodes for a show can be listed using eps and the number in the []'s from the output of the last find command  <br>
	`iView $ eps 0`  <br>
3. Get the show using get and the number in the []'s from the output of the last eps command  <br>
	`iView $ get 1`  <br>
			
### Basic Usage Example:

	iView $ find 7
	[0] 7.30 9 eps
	[1] That '70s Show 10 eps
	iView $ eps 0
	7.30:
		 [0] [None] 7.30 12/12/2014
		 [1] [None] 7.30 11/12/2014
		 [2] [None] 7.30 10/12/2014
		 [3] [None] 7.30 9/12/2014
		 --- extra entries have been removed ---
	iView $ get 1

Credit
======

2009-2011	Jeremy Visser <jeremy@visser.name>  
2011-	Martin Panter <vadmium@gmail.com>  
2014-	Scott Ramsay <scottramsay64@gmail.com>  

:wq
