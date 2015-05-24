from .utils import fastforward
from struct import Struct
from .utils import read_int, read_strict
from .utils import setitem
from io import SEEK_CUR

def main():
    from sys import stdin
    
    def dump(dict):
        items = ("{}: {!r}".format(n, v) for [n, v] in sorted(dict.items()))
        return "; ".join(items)
    
    flv = stdin.buffer
    print("header", dump(read_file_header(flv)))
    
    while True:
        offset = flv.tell()
        tag = read_tag_header(flv)
        if tag is None:
            break
        print(offset, dump(tag))
        
        parser = tag_parsers.get(tag["type"])
        if parser:
            parsed = parser(flv, tag)
            print(" ", dump(parsed))
        fastforward(flv, tag["length"] + 4)  # Including trailing tag size

def write_file_header(flv, audio=True, video=True):
    flv.write(SIGNATURE)
    flv.write(bytes((FILE_VERSION,)))
    flv.write(bytes((audio << 2 | video << 0,)))
    flv.write(FILE_HEADER_LENGTH.to_bytes(4, "big"))  # Body offset
    
    flv.write((0).to_bytes(4, "big"))  # Previous tag size field

def read_file_header(flv):
    signature = read_strict(flv, 3)
    if signature != SIGNATURE:
        raise ValueError(repr(signature))
    (version, flags) = read_strict(flv, 2)
    if version != FILE_VERSION:
        raise ValueError(version)
    body = read_int(flv, 4)
    fastforward(flv, body - FILE_HEADER_LENGTH + 4)  # Skip prev. tag size
    return dict(
        audio=bool(flags & 1 << 2),
        video=bool(flags & 1 << 0),
    )

SIGNATURE = b"FLV"
FILE_VERSION = 1
FILE_HEADER_LENGTH = len(SIGNATURE) + 2 + 4

def write_scriptdata(flv, metadata):
    flv.write(bytes((TAG_SCRIPTDATA,)))
    flv.write(len(metadata).to_bytes(3, "big"))
    flv.write((0).to_bytes(3, "big"))  # Timestamp
    flv.write(bytes((0,)))  # Timestamp extension
    flv.write((0).to_bytes(3, "big"))  # Stream id
    flv.write(metadata)
    flv.write((TAG_HEADER_LENGTH + len(metadata)).to_bytes(4, "big"))

def read_tag_header(flv):
    flags = flv.read(1)
    if not flags:
        return None
    (flags,) = flags
    length = read_int(flv, 3)
    timestamp = read_int(flv, 3)
    (extension,) = SBYTE.unpack(read_strict(flv, 1))
    streamid = read_int(flv, 3)
    return dict(
        filter=bool(flags >> 5 & 1),
        type=flags >> 0 & 0x1F,
        length=length,
        timestamp=timestamp | extension << 24,
        streamid=streamid,
    )
SBYTE = Struct("=b")

TAG_HEADER_LENGTH = 1 + 3 + 3 + 1 + 3

def read_prev_tag(flv):
    flv.seek(-4, SEEK_CUR)
    length = read_int(flv, 4)
    if not length:
        return None
    flv.seek(-4 - length, SEEK_CUR)
    return read_tag_header(flv)

tag_parsers = dict()

TAG_AUDIO = 8
@setitem(tag_parsers, TAG_AUDIO)
def parse_audio_tag(flv, tag):
    (flags,) = read_strict(flv, 1)
    tag["length"] -= 1
    result = dict(
        format=flags >> 4 & 0xF,
        rate=flags >> 2 & 3,
        size=flags >> 1 & 1,
        type=flags >> 0 & 1,
    )
    if result["format"] == FORMAT_AAC:
        (result["aac_type"],) = read_strict(flv, 1)
        tag["length"] -= 1
    return result

FORMAT_AAC = 10
AAC_HEADER = 0

TAG_VIDEO = 9
@setitem(tag_parsers, TAG_VIDEO)
def parse_video_tag(flv, tag):
    (flags,) = read_strict(flv, 1)
    tag["length"] -= 1
    result = dict(
        frametype=flags >> 4 & 0xF,
        codecid=flags >> 0 & 0xF,
    )
    if result["codecid"] == CODEC_AVC:
        (result["avc_type"],) = read_strict(flv, 1)
        tag["length"] -= 1
    return result

CODEC_AVC = 7
AVC_HEADER = 0

TAG_SCRIPTDATA = 18
@setitem(tag_parsers, TAG_SCRIPTDATA)
def parse_scriptdata(stream, tag=None):
    name = parse_scriptdatavalue(stream)
    value = parse_scriptdatavalue(stream)
    if tag is not None:
        tag["length"] = 0
    return dict(name=name, value=value)

def parse_scriptdatavalue(stream):
    type = read_int(stream, 1)
    return scriptdatavalue_parsers[type](stream)

scriptdatavalue_parsers = dict()

@setitem(scriptdatavalue_parsers, 0)
def parse_number(stream):
    (number,) = DOUBLE_BE.unpack(read_strict(stream, DOUBLE_BE.size))
    return number
DOUBLE_BE = Struct(">d")

@setitem(scriptdatavalue_parsers, 1)
def parse_boolean(stream):
    return bool(read_int(stream, 1))

@setitem(scriptdatavalue_parsers, 2)
def parse_string(stream):
    length = read_int(stream, 2)
    return read_strict(stream, length)

@setitem(scriptdatavalue_parsers, 3)
def parse_object(stream):
    array = dict()
    while True:
        name = parse_string(stream)
        value = parse_scriptdatavalue(stream)
        if value is StopIteration:
            return array
        array[name.decode("ascii")] = value

@setitem(scriptdatavalue_parsers, 8)
def parse_ecma_array(stream):
    fastforward(stream, 4)  # Approximate length
    return parse_object(stream)

@setitem(scriptdatavalue_parsers, 9)
def parse_end(stream):
    return StopIteration

@setitem(scriptdatavalue_parsers, 10)
def parse_array(stream):
    length = read_int(stream, 4)
    return tuple(parse_scriptdatavalue(stream) for _ in range(length))

if __name__ == "__main__":
    main()
