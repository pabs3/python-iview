#!/usr/bin/python3
import json
import cherrypy
import random
import string
import os
import iview.comm
import iview.fetch
import datetime
import threading

class downloadItem:
    def __init__(self, ep, url, folder):
        self.ep = ep
        self.url = url
        self.title = ep.get('title')
        self.stopped = False
        self.failed = False
        self.going = False
        self.doneIt = False
        self.percent = 0
        if folder.endswith(os.sep):
            self.folder = folder
        else:
            self.folder = folder + os.sep
        if not os.path.exists(self.folder):
            os.makedirs(self.folder, exist_ok=True)
        self.filename = self.folder + iview.fetch.descriptive_filename(self.title, self.title, url)
        self.job = iview.fetch.fetch_program(url=ep.get('url'), item=ep, dest_file=self.filename, frontend=self)
        self.job.start()

    def set_fraction(self, percent):
        self.percent = percent
        self.going = True
        self.started = True

    def set_size(self, size):
        self.size = size
        self.going = True
        self.started = True

    def get_display(self):
        if self.going:
            def trunk(n, dp):
                return float(int(n*10**dp)/10**dp)
            return '{:.1%} {} {} MB'.format(self.percent, self.title, trunk(self.size / 1e6, 1))
        elif self.doneIt:
            return 'Done: {}'.format(self.title)
        elif self.stopped:
            return 'Stopped: {}'.format(self.title)
        elif self.failed:
            return 'Failed: {}'.format(self.title)
        else:
            return 'Starting: {}'.format(self.title)

    def update_display(self):
        listDownloads.insert(0, self.get_display())

    def done(self, stopped=False, failed=False):
        self.doneIt = True
        self.going = False
        self.stopped = stopped
        self.failed = failed

iview.comm.get_config()
config = {}
downloads = []
config['index'] = iview.comm.get_keyword('index') # Makes startup much longer

def encodeData(data):
    def date_handler(obj):
        if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
            return obj.isoformat()
        else:
            return json.dumps(obj)
    return json.dumps(data, default=date_handler)

'''
Returns a member of the set `setAs` 
Also updates the set if the member is missing or `force=True`
'''
def lazyGetPut(lazyA, key, setAs, force=False):
    if force:
        x = setAs[key] = lazyA()
    else:
        try:
            x = setAs[key]
        except KeyError:
            x = setAs[key] = lazyA()
    return x

#unused
def inSet(key, xSet):
    try:
        x = xSet[key]
        return True
    except KeyError:
        return False

class MainApp(object):
    def __init__(self):
        pass

    @cherrypy.expose
    def about(self):
        return '''Python iView Web API

Uses the following libraries:
* CherryPy <http://www.cherrypy.org> <https://bitbucket.org/cherrypy/cherrypy/src/tip/cherrypy/LICENSE.txt> (BSD)
* Python iView <https://github.com/sramsay64/python-iview> <https://github.com/sramsay64/python-iview/blob/master/LICENSE> (GPL 3)

2009-2011 Jeremy Visser jeremy@visser.name
2011- Martin Panter vadmium@gmail.com
2014- Scott Ramsay scottramsay64@gmail.com'''

    @cherrypy.expose
    def auth(self):
        auth = iview.comm.get_auth()
        x = {}
        for key in ['host', 'token', 'tokenhd', 'server', 'playpath_prefix', 'free']:
            value = auth.get(key)
            if value is not None:
                a = '{}: {}'.format(key, value)
                x[key]=value
        return encodeData(x)

    def indexRaw(self, force=False):
        def lazyA():
            print('Downloading iView index')
            return iview.comm.get_keyword('index')
        return lazyGetPut(lazyA, 'index', config, force=force)

    @cherrypy.expose
    def index(self, force=False):
        return encodeData(self.indexRaw(force=force))

    def getShowRaw(self, showId=None):
        foundShows = [] #Should only contain one or zero elements
        for show in self.indexRaw():
            if show['id'] == showId:
                foundShows.append(show)
        return foundShows

    @cherrypy.expose
    def getShow(self, showId=None):
        return encodeData(self.getShowRaw(showId=showId))

    def getEpRaw(self, showId=None, epId=None):
        foundEps = [] #Should only contain one or zero elements
        for show in self.getShowRaw(showId=showId):
            for ep in show['items']:
                if ep['id'] == epId:
                    foundEps.append(ep)
        return foundEps

    @cherrypy.expose
    def getEp(self, showId=None, epId=None):
        return encodeData(self.getEpRaw(showId=showId, epId=epId))

    def listDownloadsRaw(self):
        infos = []
        for d in downloads:
            info = {
                'title': d.title,
                'stopped': d.stopped,
                'failed': d.failed,
                'going': d.going,
                'doneIt': d.doneIt,
                'percent': float(str(d.percent)[:5]),
                'folder': d.folder,
                'filename': d.filename,
                #'going': d.going
            }
            infos.append(info)
        return infos

    @cherrypy.expose
    def listDownloads(self):
        return encodeData(self.listDownloadsRaw())

    def downloadRaw(self, showId=None, epId=None, folder=None):
        ep = self.getEpRaw(showId=showId, epId=epId)[0]
        def do():
            global downloads
            downloads.append(downloadItem(ep, ep.get('url'), folder))
        t = threading.Thread(target=do)
        t.setName('Dl-{}'.format(ep.get('title')))
        t.start()

    @cherrypy.expose
    def download(self, showId=None, epId=None, folder=None):
        #return 'Comming-Soon'
        return encodeData(self.downloadRaw(showId=showId, epId=epId, folder=folder))

    @cherrypy.expose
    def test(self):
        return 'DEBUG TEST'

if __name__ == '__main__':
    conf = {'/': {'tools.sessions.on': True}}
    cherrypy.quickstart(MainApp(), '/', conf)
