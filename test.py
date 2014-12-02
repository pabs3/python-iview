#! /usr/bin/env python3

from unittest import TestCase
import os.path
import imp
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import sys
from io import BytesIO, TextIOWrapper
from iview.utils import fastforward
from errno import EPIPE, ECONNRESET

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
            substattr(self.iview_cli.iview.fetch, fetch_program):
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
        try:
            self.iview_gtk = load_script(path, "iview-gtk")
        except ImportError as err:
            self.skipTest(err)
    
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

import iview.utils
import urllib.request
import http.client

class TestPersistentHttp(TestCase):
    def setUp(self):
        TestCase.setUp(self)
        self.connection = iview.utils.PersistentConnectionHandler()
        self.addCleanup(self.connection.close)
        self.session = urllib.request.build_opener(self.connection)

class TestLoopbackHttp(TestPersistentHttp):
    def setUp(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from threading import Thread
        
        class RequestHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            
            self.close_connection = False
            
            def do_GET(handler):
                handler.send_response(200)
                handler.send_header("Content-Length", format(6))
                handler.end_headers()
                handler.wfile.write(b"body\r\n")
                handler.close_connection = self.close_connection
            
            def do_POST(handler):
                length = int(handler.headers["Content-Length"])
                fastforward(handler.rfile, length)
                
                handler.send_response(200)
                handler.send_header("Content-Length", format(6))
                handler.end_headers()
                handler.wfile.write(b"body\r\n")
                handler.close_connection = self.close_connection
            
            self.handle_calls = 0
            def handle(*pos, **kw):
                self.handle_calls += 1
                return BaseHTTPRequestHandler.handle(*pos, **kw)
        
        server = HTTPServer(("localhost", 0), RequestHandler)
        self.addCleanup(server.server_close)
        self.url = "http://localhost:{}".format(server.server_port)
        thread = Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        return TestPersistentHttp.setUp(self)

    def test_reuse(self):
        """Test existing connection is reused"""
        with self.session.open(self.url + "/one") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertEqual(1, self.handle_calls, "Server handle() not called")
        
        with self.session.open(self.url + "/two") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertEqual(1, self.handle_calls, "Unexpected handle() call")
    
    def test_close_empty(self):
        """Test connection closure seen as empty response"""
        self.close_connection = True
        
        with self.session.open(self.url + "/one") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertEqual(1, self.handle_calls,
            "Server handle() not called for /one")
        
        # Idempotent request should be retried
        with self.session.open(self.url + "/two") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertEqual(2, self.handle_calls,
            "Server handle() not called for /two")
        
        # Non-idempotent request should not be retried
        with self.assertRaises(http.client.BadStatusLine):
            self.session.open(self.url + "/post", b"data")
        self.assertEqual(2, self.handle_calls,
            "Server handle() retried for POST")
    
    def test_close_error(self):
        """Test connection closure reported as connection error"""
        self.close_connection = True
        with self.session.open(self.url + "/one") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertEqual(1, self.handle_calls,
            "Server handle() not called for /one")
        
        data = b"3" * 3000000
        try:
            self.session.open(self.url + "/two", data)
        except EnvironmentError as err:
            expected = {EPIPE, ECONNRESET}
            self.assertIn(err.errno, expected, "Connection error expected")
        else:
            self.fail("POST should have failed")
        self.assertEqual(1, self.handle_calls,
            "Server handle() retried for POST")

class TestMockHttp(TestPersistentHttp):
    class HTTPConnection(http.client.HTTPConnection):
        def __init__(self, host):
            http.client.HTTPConnection.__init__(self, host)
        
        def connect(self):
            self.sock = TestMockHttp.Socket(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 6\r\n"
                b"\r\n"
                b"body\r\n"
            )
    
    class Socket:
        def __init__(self, data):
            self.data = data
        def sendall(self, *pos, **kw):
            pass
        def close(self, *pos, **kw):
            self.data = None
        def makefile(self, *pos, **kw):
            return BytesIO(self.data)
    
    def run(self, *pos, **kw):
        with substattr(iview.utils, self.HTTPConnection):
            return TestPersistentHttp.run(self, *pos, **kw)
    
    def test_reuse(self):
        """Test existing connection is reused"""
        with self.session.open("http://localhost/one") as response:
            self.assertEqual(b"body\r\n", response.read())
        sock = self.connection._connection.sock
        self.assertTrue(sock.data, "Disconnected after first request")
        
        with self.session.open("http://localhost/two") as response:
            self.assertEqual(b"body\r\n", response.read())
        self.assertIs(sock, self.connection._connection.sock,
            "Socket connection changed")
        self.assertTrue(sock.data, "Disconnected after second request")
    
    def test_new_host(self):
        """Test connecting to second host"""
        with self.session.open("http://localhost/one") as response:
            self.assertEqual(b"body\r\n", response.read())
        sock1 = self.connection._connection.sock
        self.assertTrue(sock1.data, "Disconnected after first request")
        
        with self.session.open("http://otherhost/two") as response:
            self.assertEqual(b"body\r\n", response.read())
        sock2 = self.connection._connection.sock
        self.assertIsNot(sock1, sock2, "Expected new socket connection")
        self.assertTrue(sock2.data, "Disconnected after second request")

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
