#! /usr/bin/env python3

from unittest import TestCase
import os.path
import imp
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import sys
from io import BytesIO, TextIOWrapper, StringIO

try:  # Python 3.4
    from importlib import reload
except ImportError:  # Python < 3.4
    from imp import reload

class TestCli(TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "iview-cli")
        self.iview_cli = load_script(path, "iview-cli")
    
    def test_subtitles(self):
        class comm:
            def get_config():
                pass
            def get_captions(url):
                return "dummy captions"
        
        with substattr(self.iview_cli.iview, comm), \
        substattr(self.iview_cli, "stderr", StringIO()), \
        TemporaryDirectory(prefix="python-iview.") as dir:
            output = os.path.join(dir, "programme.srt")
            self.iview_cli.subtitles("programme.mp4", output)
            with substattr(sys, "stdout", TextIOWrapper(BytesIO())):
                self.iview_cli.subtitles("programme.mp4", "-")
    
    def test_proxy(self):
        class config:
            pass
        with substattr(self.iview_cli.iview, config):
            proxy = "localhost:1080"
            self.assertIsNone(self.iview_cli.parse_proxy_argument(proxy),
                "Proxy setup failed")
    
    def test_batch(self):
        with TemporaryDirectory(prefix="python-iview.") as dir:
            batch = os.path.join(dir, "batch.cfg")
            with open(batch, "w", encoding="ascii") as file:
                file.write(
                    "[batch]\n"
                    "destination: {}\n"
                    "100: Dummy series\n".format(dir)
                )
            class comm:
                def get_config():
                    pass
                def get_series_items(id):
                    return (dict(url="programme.mp4", title="Dummy title"),)
            def fetch_program(url, *, execvp, dest_file, quiet):
                nonlocal fetched
                fetched = dest_file
            with substattr(self.iview_cli.iview, comm), \
            substattr(self.iview_cli.iview.fetch, fetch_program), \
            substattr(self.iview_cli, "stderr", StringIO()):
                self.addCleanup(os.chdir, os.getcwd())
                
                fetched = None
                self.iview_cli.batch(batch)
                self.assertEqual("Dummy series - Dummy title.flv", fetched)
                
                with open(fetched, "wb"):
                    pass
                fetched = None
                self.iview_cli.batch(batch)
                self.assertIsNone(fetched, "Programme downloaded twice")

class TestF4v(TestCase):
    def test_read_box(self):
        import iview.hds
        stream = BytesIO(bytes.fromhex("0000 000E") + b"mdat")
        self.assertEqual((b"mdat", 6), iview.hds.read_box_header(stream))
        stream = BytesIO(bytes.fromhex("0000 0001") + b"mdat" +
            bytes.fromhex("0000 0000 0000 0016"))
        self.assertEqual((b"mdat", 6), iview.hds.read_box_header(stream))
        self.assertEqual((None, None), iview.hds.read_box_header(BytesIO()))

class TestGui(TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "iview-gtk")
        self.iview_gtk = load_script(path, "iview-gtk")
    
    def test_livestream(self):
        """Item with "livestream" (r) key but no "url" (n) key"""
        class view:
            def get_model():
                return model
        class model:
            def iter_children(iter):
                return (None, None)
            def get_value(iter, index):
                return iter[index]
            def append(iter, item):
                pass
            def remove(iter):
                pass
        
        def series_api(key, value=""):
            json = b"""[{
                "a": "100",
                "b": "Dummy series",
                "f": [
                    {"b": "Relative URL programme", "r": "dummy.mp4"},
                    {
                        "b": "Absolute URL programme",
                        "r": "rtmp://host/live/stream-qual@999"
                    }
                ]
            }]"""
            return self.iview_gtk.iview.comm.parser.parse_series_api(json)
        
        with substattr(self.iview_gtk.iview.comm, series_api):
            iter = (None, dict(id="100"))
            self.iview_gtk.load_series_items(view, iter, None)

class TestParse(TestCase):
    def test_date(self):
        """Test various date formats that have been seen"""
        
        import iview.parser
        from datetime import datetime
        for (input, expected) in (
            ("2014-02-07 21:00:00", datetime(2014, 2, 7, 21)),  # Normal
            ("2014-02-13", datetime(2014, 2, 13)),  # News 24
            ("0000-00-00 00:00:00", None),  # QI series 6 episode 11
        ):
            self.assertEqual(expected, iview.parser.parse_date(input))

import iview.comm

class TestProxy(TestCase):
    class DirectSocket(Exception):
        pass
    
    def run(self, *pos, **kw):
        import socket as socketmod
        def socket(*pos, **kw):
            raise self.DirectSocket("socket.socket() called")
        with substattr(socketmod, socket):
            return TestCase.run(self, *pos, **kw)
    
    def test_patching(self):
        """Ensure test case monkey patching works"""
        self.common(self.DirectSocket)
    
    def test_no_direct(self):
        """Ensure all connections are proxied"""
        import iview.config
        
        # Cannot use None to indicate module was absent
        realsocks = sys.modules.get("socks", "absent")
        
        class SocketProxied(Exception):
            pass
        class socks:
            def socksocket(*pos, **kw):
                raise SocketProxied()
            PROXY_TYPE_SOCKS5 = None
            def setdefaultproxy(*pos, **kw):
                pass
        sys.modules["socks"] = socks
        try:
            # Set dummy proxy values to enable proxy code
            with substattr(iview.config, "socks_proxy_host", True), \
            substattr(iview.config, "socks_proxy_port", True):
                reload(iview.comm)
                return self.common(SocketProxied)
        finally:
            if realsocks == "absent":
                del sys.modules["socks"]
            else:
                sys.modules["socks"] = realsocks
            reload(iview.comm)  # Reconfigure after resetting proxy settings
    
    def common(self, exception):
        from iview import hds
        self.assertRaises(exception, iview.comm.get_config)
        
        iview_config = dict(api_url=None, headers=dict(), auth_url=None)
        with substattr(iview.comm, "iview_config", iview_config):
            self.assertRaises(exception, iview.comm.get_index)
            self.assertRaises(exception, iview.comm.get_auth)
        
        self.assertRaises(exception, hds.fetch,
            "http://localhost/", "media path", "hdnea", dest_file=None)

@contextmanager
def substattr(obj, attr, *value):
    if value:
        (value,) = value
    else:
        value = attr
        attr = attr.__name__
    
    orig = getattr(obj, attr)
    try:
        setattr(obj, attr, value)
        yield value
    finally:
        setattr(obj, attr, orig)

def load_script(path, name):
    with open(path, "rb") as file:
        return imp.load_module(name, file, path,
                ("", "rb", imp.PY_SOURCE))

if __name__ == "__main__":
    import unittest
    unittest.main()
