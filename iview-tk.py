#!/usr/bin/env python3

import os
from os.path import expanduser
import threading
import iview.comm
import iview.fetch
from tkinter import Tk, N, W, E, S, Listbox, Button, Text, Label
from tkinter.constants import END
from tkinter.filedialog import askdirectory

eps = []
epNum = 0
showNum = 0
downloads = []

def trunk(n, dp):
	return float(int(n*10**dp)/10**dp)

class downloadItem:
	def __init__(self, ep, url):
		self.ep = ep
		self.url = url
		self.title = ep.get('title')
		self.stopped = False
		self.failed = False
		self.going = False
		self.doneIt = False
		self.percent = 0
		self.dir = addPathSep(folderName.get(1.0, END)[:-1])
		checkDir(self.dir)
		fname = self.dir + iview.fetch.descriptive_filename(self.title, self.title, url)
		self.job = addDownload(eps[epNum], dest_file=fname, frontend=self)
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

def checkDir(dir):
	if not os.path.exists(dir):
		os.makedirs(dir, exist_ok=True)

def about():
	print('//TODO About Button')

def addPathSep(dir):
	if dir.endswith(os.sep):
		return dir
	else:
		return dir + os.sep

def chooseDir():
	dir = addPathSep(askdirectory(initialdir=folderName.get(1.0, END)[:-1], parent=window)) # [:-1] is used to remove newline
	folderName.delete(1.0, END)
	folderName.insert(END, dir)

def refreshDownloadList():
	listDownloads.delete(0, END)
	for d in downloads:
		d.update_display()

def download():
	global listEps, listShows
	print(showNum)
	print(epNum)
	def do():
		def doGlob():
			global downloads, listDownloads
			downloads.append(downloadItem(eps[epNum], eps[epNum].get('url')))
			listDownloads.insert(0, downloads[-1].get_display())
		doGlob()
	t = threading.Thread(target=do)
	t.setName('Dl-{}'.format(eps[epNum].get('title')))
	t.start()

def addDownload(ep, dest_file=None, frontend=None):
	return iview.fetch.fetch_program(url=ep.get('url'), item=ep, dest_file=dest_file, frontend=frontend)

def indexShows():
	global listShows, index
	index = iview.comm.get_keyword('index')
	for i, x in enumerate(index):
		listShows.insert(i, x.get('title'))

def indexEps(s):
	global listEps, showNum, eps
	showNum = s
	eps = iview.comm.get_series_items(index[showNum].get('id'))
	listEps.delete(0, len(listEps.keys()))
	for i, x in enumerate(eps):
		listEps.insert(i, x.get('title'))

def indexEpsEv(*arg):
	indexEps(listShows.curselection()[0])

def setEpNumEv(*arg):
	global epNum
	epNum = listEps.curselection()[0]

def setupGui():
	global window
	global labelShows, labelEpisodes, labelDownloads
	global listShows, listEps, listDownloads
	global btnAbout, btnDownload, btnChooseFolder
	global folderFrame
	global folderName
	window = Tk()
	window.title('iView')
	window.minsize(300, 200)
	
	labelShows = Label(window, text='Shows')
	labelShows.grid(column=0, row=0, sticky=[N,S,E,W])
	
	listShows = Listbox(window)
	listShows.grid(column=0, row=1, sticky=[N,S,E,W])
	listShows.bind('<<ListboxSelect>>', indexEpsEv)
	indexShows()
	
	labelEpisodes = Label(window, text='Episodes')
	labelEpisodes.grid(column=1, row=0, sticky=[N,S,E,W])
	
	listEps = Listbox(window)
	listEps.grid(column=1, row=1, sticky=[N,S,E,W])
	listEps.bind('<<ListboxSelect>>', setEpNumEv)
	indexEps(0)
	
	labelDownloads = Label(window, text='Downloads')
	labelDownloads.grid(column=2, row=0, sticky=[N,S,E,W])
	
	listDownloads = Listbox(window)
	listDownloads.grid(column=2, row=1, sticky=[N,S,E,W])
	
	btnAbout = Button(window, text='About', command=about)
	btnAbout.grid(column=0, row=2, sticky=[N,S,E,W])
	
	btnDownload = Button(window, text='Download', command=download)
	btnDownload.grid(column=1, row=2, sticky=[N,S,E,W])
	
	btnChooseFolder = Button(window, text='Choose Download Folder', command=chooseDir)
	btnChooseFolder.grid(column=2, row=2, sticky=[N,S,E,W])
	
	folderName = Text(window, height=1)
	folderName.grid(column=0, row=3, columnspan=3)
	folderName.insert(END, expanduser("~")+(':Videos:iView:'.replace(':', os.sep)))
	
	window.columnconfigure(0, weight=1)
	window.columnconfigure(1, weight=1)
	window.columnconfigure(2, weight=1)
	window.rowconfigure(1, weight=1)
	
	def updateDownloadList():
		refreshDownloadList()
		window.after(1000, updateDownloadList)
	dlListThrd = threading.Thread(target=updateDownloadList)
	dlListThrd.setName('Update Download List')
	dlListThrd.start()

if __name__ == '__main__':
	iview.comm.get_config()
	setupGui()
	window.mainloop()
