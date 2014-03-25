"""Adobe HTTP Dynamic Streaming (HDS) client

Other implementations:
* KSV's PHP script,
    https://github.com/K-S-V/Scripts/blob/master/AdobeHDS.php
* Livestreamer
* FFMPEG branch:
    https://github.com/ottomatic/ffmpeg/blob/hds/libavformat/hdsdec.c
* https://github.com/pacomod/replaydlr/blob/master/src/DownloaderF4m.py
    (originally PluzzDl.py)
"""

import xml.etree.cElementTree as ElementTree
from base64 import b64encode, b64decode
from urllib.request import urlopen
import hmac
from hashlib import sha256
from .utils import CounterWriter, ZlibDecompressorWriter, TeeWriter
from .utils import streamcopy, fastforward
from shutil import copyfileobj
import urllib.request
from .utils import PersistentConnectionHandler
from .utils import urlencode_param
from sys import stderr
from urllib.parse import urljoin
from io import BytesIO
from .utils import xml_text_elements
from . import flvlib
from .utils import read_int, read_string
from .utils import WritingReader

def fetch(*pos, dest_file, frontend=None, abort=None, player=None, key=None,
**kw):
    url = manifest_url(*pos, **kw)
    
    with PersistentConnectionHandler() as connection:
        session = urllib.request.build_opener(connection)
        
        manifest = get_manifest(url, session)
        url = manifest["baseURL"]
        player = player_verification(manifest, player, key)
        
        duration = manifest.get("duration")
        if duration:
            duration = float(duration) or None
        else:
            duration = None
        
        # TODO: determine preferred bitrate, max bitrate, etc
        media = manifest["media"][0]  # Just pick the first one!
        href = media.get("href")
        if href is not None:
            href = urljoin(url, href)
            bitrate = media.get("bitrate")  # Save this in case the child manifest does not specify a bitrate
            raise NotImplementedError("/manifest/media/@href -> child manifest")
        
        bootstrap = get_bootstrap(media,
            session=session, url=url, player=player)
        
        media_url = media["url"] + bootstrap["movie_identifier"]
        if "highest_quality" in bootstrap:
            media_url += bootstrap["highest_quality"]
        if "server_base_url" in bootstrap:
            media_url = urljoin(bootstrap["server_base_url"], media_url)
        media_url = urljoin(url, media_url)
        
        metadata = media.get("metadata")
        
        if not duration:
            if bootstrap["time"]:
                duration = bootstrap["time"] / bootstrap["timescale"]
            elif metadata:
                scriptdata = flvlib.parse_scriptdata(BytesIO(metadata))
                assert scriptdata["name"] == b"onMetaData"
                duration = scriptdata["value"].get("duration")
        
        flv = CounterWriter(dest_file)  # Track size even if piping to stdout
        
        # Assume audio and video tags will be present
        flvlib.write_file_header(flv, audio=True, video=True)
        
        if metadata:
            flvlib.write_scriptdata(flv, metadata)
        
        progress_update(frontend, flv, 0, duration)
        
        segs = iter_segs(bootstrap["seg_runs"])
        first = True
        for (frag, endtime) in iter_frags(bootstrap["frag_runs"]):
            seg = next(segs)
            frag_url = "{}Seg{}-Frag{}".format(media_url, seg, frag)
            if player:
                frag_url = urljoin(frag_url, "?" + player)
            response = session.open(frag_url)
            
            while True:
                if abort and abort.is_set():
                    raise SystemExit()
                (boxtype, boxsize) = read_box_header(response)
                if not boxtype:
                    break
                
                if boxtype == b"mdat":
                    # Strip AAC and AVC sequence headers from fragments other
                    # than the first fragment. This assumes that the header
                    # tags only appear as the first tag of their type in each
                    # fragment. This way the code avoids unnecessarily
                    # scanning for them, which is much slower than simply
                    # copying the stream.
                    if not first:
                        audio_found = False
                        video_found = False
                        while boxsize and not (audio_found and video_found):
                            cache = BytesIO()
                            proxy = WritingReader(response, cache)
                            tag = flvlib.read_tag_header(proxy)
                            
                            if tag["type"] == flvlib.TAG_AUDIO:
                                audio_found = True
                                parsed = flvlib.parse_audio_tag(proxy, tag)
                                skip = (parsed.get("aac_type") ==
                                    flvlib.AAC_HEADER)
                            elif tag["type"] == flvlib.TAG_VIDEO:
                                video_found = True
                                parsed = flvlib.parse_video_tag(proxy, tag)
                                skip = (parsed.get("avc_type") ==
                                    flvlib.AVC_HEADER)
                            else:
                                skip = False
                            
                            boxsize -= cache.tell()
                            tag["length"] += 4  # Trailing tag size field
                            if skip:
                                fastforward(response, tag["length"])
                            else:
                                flv.write(cache.getvalue())
                                streamcopy(response, flv, tag["length"])
                            boxsize -= tag["length"]
                            assert boxsize >= 0
                    
                    streamcopy(response, flv, boxsize)
                    first = False
                else:
                    fastforward(response, boxsize)
            
            endtime /= bootstrap["frag_timescale"]
            progress_update(frontend, flv, endtime, duration)
        if not frontend:
            print(file=stderr)

def get_bootstrap(media, *, session, url, player=None):
    bootstrap = media["bootstrapInfo"]
    bsurl = bootstrap.get("url")
    if bsurl is not None:
        bsurl = urljoin(url, bsurl)
        if player:
            bsurl = urljoin(bsurl, "?" + player)
        with session.open(bsurl) as response:
            bootstrap = response.read()
    else:
        bootstrap = BytesIO(bootstrap["data"])
    
    (type, _) = read_box_header(bootstrap)
    assert type == b"abst"
    
    result = dict()
    
    fastforward(bootstrap, 1 + 3 + 4)  # Version, flags, bootstrap version
    
    flags = read_int(bootstrap, 1)
    flags >> 6  # Profile
    bool(flags & 0x20)  # Live flag
    bool(flags & 0x10)  # Update flag
    
    result["timescale"] = read_int(bootstrap, 4)  # Time scale
    result["time"] = read_int(bootstrap, 8)  # Media time at end of bootstrap
    fastforward(bootstrap, 8)  # SMPTE timecode offset
    
    result["movie_identifier"] = read_string(bootstrap).decode("utf-8")
    
    count = read_int(bootstrap, 1)  # Server table
    for _ in range(count):
        entry = read_string(bootstrap)
        if "server_base_url" not in result:
            result["server_base_url"] = entry.decode("utf-8")
    
    count = read_int(bootstrap, 1)  # Quality table
    for _ in range(count):
        quality = read_string(bootstrap)
        if "highest_quality" not in result:
            result["highest_quality"] = quality.decode("utf-8")
    
    read_string(bootstrap)  # DRM data
    read_string(bootstrap)  # Metadata
    
    # Read segment and fragment run tables. Read the first table of each type
    # that is understood, and skip any subsequent ones.
    count = read_int(bootstrap, 1)
    for _ in range(count):
        if "seg_runs" not in result:
            (qualities, runs) = read_asrt(bootstrap)
            if not qualities or result.get("highest_quality") in qualities:
                result["seg_runs"] = runs
        else:
            skip_box(bootstrap)
    if "seg_runs" not in result:
        fmt = "Segment run table not found (quality = {!r})"
        raise LookupError(fmt.format(result.get("highest_quality")))
    
    count = read_int(bootstrap, 1)
    for _ in range(count):
        if "frag_runs" not in result:
            (qualities, runs, timescale) = read_afrt(bootstrap)
            if not qualities or result.get("highest_quality") in qualities:
                result["frag_runs"] = runs
                result["frag_timescale"] = timescale
        else:
            skip_box(bootstrap)
    if "frag_runs" not in result:
        fmt = "Fragment run table not found (quality = {!r})"
        raise LookupError(fmt.format(result.get("highest_quality")))
    
    return result

def iter_segs(seg_runs):
    # For each run of segments
    for (i, run) in enumerate(seg_runs):
        # For each segment in the run
        seg = run["first"]
        if i + 1 < len(seg_runs):
            end = seg_runs[i + 1]["first"]
        else:
            end = None
        while end is None or seg < end:
            # For each fragment in the segment
            for _ in range(run["frags"]):
                yield seg
            seg += 1

def iter_frags(frag_runs):
    # For each run of fragments
    for (i, run) in enumerate(frag_runs):
        discontinuity = run.get("discontinuity")
        if discontinuity is not None:
            if discontinuity == DISCONT_END:
                break
            continue
        
        start = run["first"]
        time = run["timestamp"]
        
        # Find the next run to determine how many fragments in this run.
        # Assume a single fragment if end of table, end of stream or fragment
        # numbering discontinuity found. Skip over other kinds of
        # discontinuities.
        for next in frag_runs[i + 1:]:
            discontinuity = next.get("discontinuity")
            if discontinuity is None:
                end = next["first"]
                break
            if discontinuity == DISCONT_END or discontinuity & DISCONT_FRAG:
                end = start + 1
                break
        else:
            end = start + 1
        
        for frag in range(start, end):
            time += run["duration"]
            yield (frag, time)

def progress_update(frontend, flv, time, duration):
    size = flv.tell()
    
    if frontend:
        if duration:
            frontend.set_fraction(time / duration)
        frontend.set_size(size)
    
    else:
        if duration:
            duration = "/{:.1F}".format(duration)
        else:
            duration = ""
        
        stderr.write("\r{:.1F}{} s; {:.1F} MB".format(
            time, duration, size / 1e6))
        stderr.flush()

def manifest_url(url, file, hdnea=None):
    file += "/manifest.f4m?hdcore="
    if hdnea:
        file += "&hdnea=" + urlencode_param(hdnea)
    return urljoin(url, file)

def get_manifest(url, session):
    """Downloads the manifest specified by the URL and parses it
    
    Returns a dict() representing the top-level XML element names and text
    values of the manifest. Special items are:
    
    "baseURL": Defaults to the "url" parameter if the manifest is missing a
        <baseURL> element.
    "media": A sequence of dict() objects representing the attributes and
        text values of the <media> elements.
    
    A "media" dictionary contain the special key "bootstrapInfo", which holds
    a dict() object representing the attributes of the associated <bootstrap-
    Info> element. Each "bootstrapInfo" dictionary may be shared by more than
    one "media" item. A "bootstrapInfo" dictionary may contain the special
    key "data", which holds the associated bootstrap data."""
    
    with session.open(url) as response:
        manifest = ElementTree.parse(response).getroot()
    
    parsed = xml_text_elements(manifest, F4M_NAMESPACE)
    parsed.setdefault("baseURL", url)
    
    bootstraps = dict()
    for bootstrap in manifest.findall(F4M_NAMESPACE + "bootstrapInfo"):
        item = dict(bootstrap.items())
        
        bootstrap = bootstrap.text
        if bootstrap is not None:
            bootstrap = b64decode(bootstrap.encode("ascii"), validate=True)
            item["data"] = bootstrap
        
        bootstraps[item.get("id")] = item
    
    parsed["media"] = list()
    for media in manifest.findall(F4M_NAMESPACE + "media"):
        item = dict(media.items())
        item.update(xml_text_elements(media, F4M_NAMESPACE))
        item["bootstrapInfo"] = bootstraps[item.get("bootstrapInfoId")]
        metadata = item["metadata"].encode("ascii")
        item["metadata"] = b64decode(metadata, validate=True)
        parsed["media"].append(item)
    
    return parsed

F4M_NAMESPACE = "{http://ns.adobe.com/f4m/1.0}"

def read_asrt(bootstrap):
    (type, size) = read_box_header(bootstrap)
    if type != b"asrt":
        fastforward(bootstrap, size)
        return ((), None)
    
    fastforward(bootstrap, 1 + 3)  # Version, flags
    size -= 1 + 3
    
    qualities = set()
    count = read_int(bootstrap, 1)  # Quality segment URL modifier table
    size -= 1
    for _ in range(count):
        quality = read_string(bootstrap)
        size -= len(quality)
        qualities.add(quality.decode("utf-8"))
    
    seg_runs = list()
    count = read_int(bootstrap, 4)
    size -= 4
    for _ in range(count):
        run = dict()
        run["first"] = read_int(bootstrap, 4)  # First segment number in run
        run["frags"] = read_int(bootstrap, 4)  # Fragments per segment
        size -= 8
        seg_runs.append(run)
    assert not size
    return (qualities, seg_runs)

def read_afrt(bootstrap):
    (type, size) = read_box_header(bootstrap)
    if type != b"afrt":
        fastforward(bootstrap, size)
        return ((), None)
    
    fastforward(bootstrap, 1 + 3)  # Version, flags
    timescale = read_int(bootstrap, 4)
    size -= 1 + 3 + 4
    
    qualities = set()
    count = read_int(bootstrap, 1)  # Quality segment URL modifier table
    size -= 1
    for _ in range(count):
        quality = read_string(bootstrap)
        size -= len(quality)
        qualities.add(quality.decode("utf-8"))
    
    frag_runs = list()
    count = read_int(bootstrap, 4)
    size -= 4
    for _ in range(count):
        run = dict()
        run["first"] = read_int(bootstrap, 4)  # First fragment number in run
        run["timestamp"] = read_int(bootstrap, 8)  # Timestamp at start
        run["duration"] = read_int(bootstrap, 4)  # Duration of each fragment
        size -= 16
        if not run["duration"]:
            run["discontinuity"] = read_int(bootstrap, 1)
            size -= 1
        frag_runs.append(run)
    assert not size
    return (qualities, frag_runs, timescale)

# Discontinuity indicator values
DISCONT_END = 0
DISCONT_FRAG = 1
DISCONT_TIME = 2

def player_verification(manifest, player, key):
    pv = manifest.get("pv-2.0")
    if not pv:
        return
    (data, hdntl) = pv.split(";")
    msg = "st=0~exp=9999999999~acl=*~data={}!{}".format(data, player)
    sig = hmac.new(key, msg.encode("ascii"), sha256)
    pvtoken = "{}~hmac={}".format(msg, sig.hexdigest())
    
    # The "hdntl" parameter must be passed either in the URL or as a cookie
    return "pvtoken={}&{}".format(
        urlencode_param(pvtoken), urlencode_param(hdntl))

def skip_box(stream):
    (_, size) = read_box_header(stream)
    fastforward(stream, size)

def read_box_header(stream):
    """Returns (type, size) tuple, or (None, None) at EOF"""
    boxsize = stream.read(4)
    if not boxsize:
        return (None, None)
    boxtype = stream.read(4)
    assert len(boxsize) == 4 and len(boxtype) == 4
    boxsize = int.from_bytes(boxsize, "big")
    if boxsize == 1:
        boxsize = read_int(stream, 8)
        boxsize -= 16
    else:
        boxsize -= 8
    assert boxsize >= 0
    return (boxtype, boxsize)

SWF_VERIFICATION_KEY = b"Genuine Adobe Flash Player 001"

def swf_hash(url):
    try:
        from types import SimpleNamespace
    except ImportError:
        from shorthand import SimpleNamespace
    
    with urlopen(url) as swf:
        assert swf.read(3) == b"CWS"
        
        swf_hash = hmac.new(SWF_VERIFICATION_KEY, digestmod=sha256)
        counter = CounterWriter(SimpleNamespace(write=swf_hash.update))
        player = sha256()
        uncompressed = TeeWriter(
            counter,
            SimpleNamespace(write=player.update),
        )
        
        uncompressed.write(b"FWS")
        uncompressed.write(swf.read(5))
        with ZlibDecompressorWriter(uncompressed) as decompressor:
            copyfileobj(swf, decompressor)
        
        print(counter.tell())
        print(swf_hash.hexdigest())
        print(b64encode(player.digest()).decode('ascii'))
