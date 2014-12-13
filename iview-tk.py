#!/usr/bin/env python3

import iview.comm
import iview.fetch
from tkinter import Tk, N, W, E, S, Listbox, Button
import threading

eps = []
epNum = 0
showNum = 0

def about():
	print('//TODO About Button')

def download():
	global listEps, listShows
	print('//TODO Download Button')
	print(showNum)
	print(epNum)
	def do():
		addDownload(eps[epNum])
	t = threading.Thread(target=do)
	t.setName('Dl-'+eps[epNum].get('title'))
	t.start()

def addDownload(ep):
	iview.fetch.fetch_program(ep.get('url'))

def indexShows():
	global listShows, index
	index = iview.comm.get_index()
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

def setupGui():
	global window, btnAbout, btnDownload, listShows, listEps, listDownloads
	window = Tk()
	window.title('iView')
	
	listShows = Listbox(window)
	listShows.grid(column=0, row=0, sticky=[N,S,E,W])
	listShows.bind('<<ListboxSelect>>', indexEpsEv)
	indexShows()
	
	listEps = Listbox(window)
	listEps.grid(column=1, row=0, sticky=[N,S,E,W])
	indexEps(0)
	
	listDownloads = Listbox(window)
	listDownloads.grid(column=2, row=0, sticky=[N,S,E,W])
	
	btnAbout = Button(window, text='About', command=about)
	btnAbout.grid(column=0, row=1, sticky=[N,S,E,W])
	
	btnDownload = Button(window, text='Download', command=download)
	btnDownload.grid(column=1, row=1)
	
	window.columnconfigure(0, weight=1)
	window.columnconfigure(1, weight=1)
	window.columnconfigure(2, weight=1)
	window.rowconfigure(0, weight=1)

if __name__ == '__main__':
	iview.comm.get_config()
	setupGui()
	window.mainloop();