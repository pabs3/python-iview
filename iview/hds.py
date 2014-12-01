"""Adobe HTTP Dynamic Streaming (HDS) client

Other implementations:
* KSV's PHP script,
    https://github.com/K-S-V/Scripts/blob/master/AdobeHDS.php
* Livestreamer
* FFMPEG branch:
    https://github.com/ottomatic/ffmpeg/blob/hds/libavformat/hdsdec.c
* https://github.com/pacomod/replaydlr/blob/master/src/DownloaderF4m.py
    (originally PluzzDl.py)

Flash Video Specification 10.1
(including FLV, bootstrap, and fragment formats):
http://download.macromedia.com/f4v/video_file_format_spec_v10_1.pdf
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
from .utils import PersistentConnectionHandler, http_get
from .utils import urlencode_param
from sys import stderr
from urllib.parse import urljoin
import io
from .utils import xml_text_elements
from . import flvlib
from .utils import read_int, read_string, read_strict
from .utils import WritingReader
from errno import ESPIPE, EBADF, EINVAL
import os
from itertools import chain

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
        
        metadata = media.get("metadata")
        
        media_url = media["url"] + bootstrap["movie_identifier"]
        if "highest_quality" in bootstrap:
            media_url += bootstrap["highest_quality"]
        if "server_base_url" in bootstrap:
            media_url = urljoin(bootstrap["server_base_url"], media_url)
        media_url = urljoin(url, media_url)
        
        flv = start_flv(dest_file,
            metadata=metadata, bootstrap=bootstrap,
            session=session, url=media_url, player=player)
        
        if not duration:
            if bootstrap["time"]:
                duration = bootstrap["time"] / bootstrap["timescale"]
            elif metadata:
                scriptdata = flvlib.parse_scriptdata(io.BytesIO(metadata))
                assert scriptdata["name"] == b"onMetaData"
                duration = scriptdata["value"].get("duration")
        
        progress_update(frontend, flv, 0, duration)
        
        segs = iter_segs(bootstrap["seg_runs"])
        strip_headers = False
        for (frag, endtime) in iter_frags(bootstrap["frag_runs"]):
            seg = next(segs)
            if abort and abort.is_set():
                raise SystemExit()
            response = get_frag(session, media_url, seg, frag, player=player)
            
            if abort and abort.is_set():
                raise SystemExit()
            buffer = frag_to_flv(response, strip_headers=strip_headers)
            copyfileobj(buffer, flv)
            endtime /= bootstrap["frag_timescale"]
            progress_update(frontend, flv, endtime, duration)
            strip_headers = True
        if not frontend:
            print(file=stderr)

def get_bootstrap(media, *, session, url, player=""):
    bootstrap = media["bootstrapInfo"]
    bsurl = bootstrap.get("url")
    if bsurl is not None:
        bsurl = urljoin(url, bsurl)
        bsurl = urljoin(bsurl, player)
        with http_get(session, bsurl, "video/abst") as response:
            bootstrap = response.read()
    else:
        bootstrap = io.BytesIO(bootstrap["data"])
    
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

def start_flv(dest_file, *, metadata, bootstrap, session, url, player=""):
    """Determine resume point, or write out start of FLV"""
    frags = resume_point(dest_file,
        metadata=metadata, bootstrap=bootstrap,
        session=session, url=url, player=player)
    if frags is not None:
        return dest_file
    
    flv = CounterWriter(dest_file)  # Track size even if piping to stdout
    
    possibly_trunc(dest_file)
    # Assume audio and video tags will be present
    flvlib.write_file_header(flv, audio=True, video=True)
    
    if metadata:
        flvlib.write_scriptdata(flv, metadata)
    return flv

def resume_point(dest_file, *, metadata, bootstrap, session, url, player=""):
    try:
        start = dest_file.tell()  # Ensures file is seekable
        fd = dest_file.fileno()
    except io.UnsupportedOperation:
        return None
    except EnvironmentError as err:
        if err.errno == ESPIPE:
            return None
        raise
    
    with os.fdopen(fd, "rb", closefd=False) as reader:
        try:
            header = flvlib.read_file_header(reader)
            if header != dict(audio=True, video=True):
                raise ValueError(header)
            
            print("Scanning existing FLV file", file=stderr)
            if metadata:
                tag = flvlib.read_tag_header(reader)
                if tag is None:
                    raise EOFError()
                expected = dict(
                    type=flvlib.TAG_SCRIPTDATA,
                    filter=False,
                    length=len(metadata),
                    timestamp=0,
                    streamid=0,
                )
                if tag != expected:
                    raise ValueError(tag)
                data = read_strict(reader, tag["length"])
                if data != metadata:
                    raise ValueError()
                fastforward(reader, 4)
            
            tag = scan_last_tag(reader)
        except EOFError:
            pass
        except EnvironmentError as err:
            if err.errno != EBADF:  # Reading from write-only file descriptor
                raise
        else:
            # Resume at the fragment containing the last timestamp. Usually
            # this means that the last fragment will be downloaded a second
            # time, but it ensures that the complete fragment is written out
            # in case it was previously truncated.
            last_ts = tag["timestamp"]
            [run_index, run, ts_offset, frag_runs] = find_frag_run(
                bootstrap, last_ts, 1000)
            for _ in range(3):  # Retry if fragment starts too late
                offset = ts_offset * run["span"] // run["run_duration"]
                frag_index = run_index + offset
                segs = iter_segs(bootstrap, frag_index)
                frag = run["start"] + offset
                response = get_frag(session, url, next(segs), frag,
                    player=player)
                buffer = io.BytesIO()
                proxy = WritingReader(response, buffer)
                boxsize = next(mdat_boxes(proxy))
                tag = flvlib.read_tag_header(proxy)
                if flvlib.TAG_HEADER_LENGTH + tag["length"] + 4 > boxsize:
                    raise EOFError("Tag extends past end of box")
                if tag["timestamp"] <= last_ts:
                    break
                raise NotImplementedError("TODO: Cancel fragment and try an earlier one")
            else:
                msg = "Failed estimating resume fragment after 3 tries"
                raise OverflowError(msg)
            
            # Copy rest of fragment into buffer, now timestamp is verified
            for _ in range(32 * 1024 // 64):
                if not proxy.read(64 * 1024):
                    break
            else:
                raise OverflowError("Fragment exceeds 32 MiB")
            buffer.seek(0)
            
            # Assumes timestamps in different fragments are unequal
            seek_backwards(reader, tag["timestamp"])
            msg = "Resuming FLV from {:.1F} s ({:.1F} MB)"
            timestamp = tag["timestamp"] / 1000
            size = (reader.tell() - start) / 1e6
            print(msg.format(timestamp, size), file=stderr)
            
            buffer = frag_to_flv(buffer, strip_headers=frag_index)
            dest_file.seek(reader.tell())
            possibly_trunc(dest_file)
            copyfileobj(buffer, dest_file)
    
    # EOF before first tag, or file descriptor not readable
    dest_file.seek(start)
    return None

def scan_last_tag(reader):
    good_tag = None
    timestamp = None
    try:
        while True:
            tag_end = reader.tell()
            tag = flvlib.read_tag_header(reader)
            if tag is None:
                raise EOFError()
            
            # Ensure timestamps are not out of order
            if timestamp is not None and tag["timestamp"] < timestamp:
                raise ValueError(tag["timestamp"])
            timestamp = tag["timestamp"]
            
            fastforward(reader, tag["length"] + 4)
            good_tag = tag
    except EOFError:
        if not good_tag:
            raise
    reader.seek(tag_end - 4)
    return good_tag

def get_frag(session, url, seg, frag, player=""):
    url = "{}Seg{}-Frag{}".format(url, seg, frag)
    url = urljoin(url, player)
    return http_get(session, url, ("video/f4f",))

def frag_to_flv(frag, strip_headers):
    strip_audio = strip_headers
    strip_video = strip_headers
    buffer = io.BytesIO()
    for boxsize in mdat_boxes(frag):
        # Strip AAC and AVC sequence headers from fragments other than the
        # first fragment. This assumes that the header tags only appear as
        # the first tag of their type in each fragment. This way the code
        # avoids unnecessarily scanning for them, which is much slower than
        # simply copying the stream.
        while boxsize and (strip_audio or strip_video):
            cache = io.BytesIO()
            proxy = WritingReader(frag, cache)
            tag = flvlib.read_tag_header(proxy)
            
            if tag["type"] == flvlib.TAG_AUDIO:
                strip_audio = False
                parsed = flvlib.parse_audio_tag(proxy, tag)
                skip = parsed.get("aac_type") == flvlib.AAC_HEADER
            elif tag["type"] == flvlib.TAG_VIDEO:
                strip_video = False
                parsed = flvlib.parse_video_tag(proxy, tag)
                skip = parsed.get("avc_type") == flvlib.AVC_HEADER
            else:
                skip = False
            
            boxsize -= cache.tell()
            tag["length"] += 4  # Trailing tag size field
            if skip:
                fastforward(frag, tag["length"])
            elif tag["length"] > 10e6:
                raise OverflowError("FLV tag over 10 MB")
            else:
                buffer.write(cache.getvalue())
                streamcopy(frag, buffer, tag["length"])
            boxsize -= tag["length"]
            if boxsize < 0:
                raise EOFError("Tag extends past end of box")
        
        streamcopy(frag, buffer, boxsize)
    
    buffer.seek(0)
    return buffer

def mdat_boxes(frag):
    for _ in range(100):
        (boxtype, boxsize) = read_box_header(frag)
        if not boxtype:
            break
        if boxtype != b"mdat":
            fastforward(frag, boxsize)
            continue
        yield boxsize
    else:
        raise OverflowError("100 or more boxes in fragment")

def find_frag_run(bootstrap, timestamp, timescale):
    """Find a fragment run that probably contains the timestamp"""
    timestamp *= bootstrap["frag_timescale"]
    runs = iter(bootstrap["frag_runs"])
    flags = 0
    start_frag = None
    frag_index = 0
    while True:
        run = next(runs, dict(discontinuity=DISCONT_END))
        discontinuity = run.get("discontinuity")
        if discontinuity == DISCONT_END:
            flags |= DISCONT_FRAG | DISCONT_TIME
        elif discontinuity is not None:
            flags |= discontinuity
        if discontinuity in {None, DISCONT_END}:
            if start_frag is not None:
                if flags & DISCONT_FRAG:
                    frags = 1
                else:
                    frags = run["first"] - start_frag
                if flags & DISCONT_TIME:
                    run_duration = duration * frags
                else:
                    run_duration = (
                        run["timestamp"] - start_time)
                start_time *= timescale
                run_duration *= timescale
                ts_offset = timestamp - start_time
                if 0 <= ts_offset < run_duration:
                    run_info = dict(start=start_frag, span=frags,
                        start_time=start_time, run_duration=run_duration)
                    runs = chain((run,), runs)
                    return (frag_index, run_info, ts_offset, runs)
                frag_index += frags
            if discontinuity == DISCONT_END:
                raise ValueError("No fragment run found with timestamp")
            start_frag = run["first"]
            start_time = run["timestamp"]
            duration = run["duration"]
            flags = 0

def seek_backwards(reader, timestamp):
    while True:
        length = read_int(reader, 4)
        if not length:
            break
        reader.seek(-4 - length, io.SEEK_CUR)
        tag = flvlib.read_tag_header(reader)
        if tag["timestamp"] < timestamp:
            reader.seek(+tag["length"] + 4, io.SEEK_CUR)
            break
        reader.seek(-flvlib.TAG_HEADER_LENGTH - 4, io.SEEK_CUR)

def iter_segs(bootstrap, start=0):
    # For each run of segments
    for (i, run) in enumerate(bootstrap["seg_runs"]):
        # For each segment in the run
        seg = run["first"]
        if i + 1 < len(bootstrap["seg_runs"]):
            end = bootstrap["seg_runs"][i + 1]["first"]
            frags = (end - seg) * run["frags"]
            if start >= frags:
                start -= frags
                continue
        else:
            end = None
        [segs, start] = divmod(start, run["frags"])
        seg += segs
        while end is None or seg < end:
            # For each fragment in the segment
            for _ in range(start, run["frags"]):
                yield seg
            start = 0
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
    
    with http_get(session, url, ("video/f4m",)) as response:
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
        
        # Beware of actual fragment timestamps and durations drifting from
        # fragment run table values
        run["timestamp"] = read_int(bootstrap, 8)  # Timestamp at start
        run["duration"] = read_int(bootstrap, 4)  # Duration of each fragment
        
        size -= 16
        if not run["duration"]:
            del run["first"], run["timestamp"]  # Not used for discontinuity
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
        return ""
    (data, hdntl) = pv.split(";")
    msg = "st=0~exp=9999999999~acl=*~data={}!{}".format(data, player)
    sig = hmac.new(key, msg.encode("ascii"), sha256)
    pvtoken = "{}~hmac={}".format(msg, sig.hexdigest())
    
    # The "hdntl" parameter must be passed either in the URL or as a cookie
    return "?pvtoken={}&{}".format(
        urlencode_param(pvtoken), urlencode_param(hdntl))

def skip_box(stream):
    (_, size) = read_box_header(stream)
    fastforward(stream, size)

def read_box_header(stream):
    """Returns (type, size) tuple, or (None, None) at EOF"""
    boxsize = stream.read(4)
    if not boxsize:
        return (None, None)
    if len(boxsize) != 4:
        raise EOFError()
    boxtype = read_strict(stream, 4)
    boxsize = int.from_bytes(boxsize, "big")
    if boxsize == 1:
        boxsize = read_int(stream, 8)
        boxsize -= 16
    else:
        boxsize -= 8
    assert boxsize >= 0
    return (boxtype, boxsize)

def possibly_trunc(file):
    """Truncate a file if supported by the file type"""
    try:
        file.truncate()
    except io.UnsupportedOperation:
        pass
    except EnvironmentError as err:
        if err.errno not in {ESPIPE, EBADF, EINVAL}:
            raise

SWF_VERIFICATION_KEY = b"Genuine Adobe Flash Player 001"

def swf_hash(url):
    try:
        from types import SimpleNamespace
    except ImportError:
        from shorthand import SimpleNamespace
    
    with urlopen(url) as swf:
        assert read_strict(swf, 3) == b"CWS"
        
        swf_hash = hmac.new(SWF_VERIFICATION_KEY, digestmod=sha256)
        counter = CounterWriter(SimpleNamespace(write=swf_hash.update))
        player = sha256()
        uncompressed = TeeWriter(
            counter,
            SimpleNamespace(write=player.update),
        )
        
        uncompressed.write(b"FWS")
        uncompressed.write(read_strict(swf, 5))
        with ZlibDecompressorWriter(uncompressed) as decompressor:
            copyfileobj(swf, decompressor)
        
        print(counter.tell())
        print(swf_hash.hexdigest())
        print(b64encode(player.digest()).decode('ascii'))
