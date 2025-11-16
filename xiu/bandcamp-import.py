#!/usr/bin/env python3

import json
import os
import shutil
import sys
import zipfile
import subprocess
import typing
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

class Response(typing.NamedTuple):
    body: str
    headers: Message
    status: int
    error_count: int = 0

    def json(self) -> typing.Any:
        """
        Decode body's JSON.

        Returns:
            Pythonic representation of the JSON object
        """
        try:
            output = json.loads(self.body)
        except json.JSONDecodeError:
            output = ""
        return output


def request(
    url: str,
    data: dict = None,
    params: dict = None,
    headers: dict = None,
    method: str = "GET",
    data_as_json: bool = True,
    error_count: int = 0,
) -> Response:
    if not url.casefold().startswith("http"):
        raise urllib.error.URLError("Incorrect and possibly insecure protocol in url")
    method = method.upper()
    request_data = None
    headers = headers or {}
    data = data or {}
    params = params or {}
    headers = {"Accept": "application/json", **headers}

    if method == "GET":
        params = {**params, **data}
        data = None

    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True, safe="/")

    if data:
        if data_as_json:
            request_data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json; charset=UTF-8"
        else:
            request_data = urllib.parse.urlencode(data).encode()

    httprequest = urllib.request.Request(
        url, data=request_data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(httprequest) as httpresponse:
            response = Response(
                headers=httpresponse.headers,
                status=httpresponse.status,
                body=httpresponse.read().decode(
                    httpresponse.headers.get_content_charset("utf-8")
                ),
            )
    except urllib.error.HTTPError as e:
        response = Response(
            body=str(e.reason),
            headers=e.headers,
            status=e.code,
            error_count=error_count + 1,
        )

    return response

def get_tag(flac, tag):
    tag = [x for x in flac if x[0].lower() == tag.lower()]
    if len(tag) > 0:
        return tag[0][1]
    return None

def get_tags(file):
	result = json.loads(subprocess.run(["ffprobe", "-loglevel", "error", "-of", "json", "-show_entries", "stream_tags:format_tags", file], capture_output=True).stdout)
	return result["format"]["tags"].items()

def get_flacs(dir):
    flacs = []
    for root, _dirs, files in os.walk(os.path.abspath(dir)):
        for file in files:
            if file.endswith(".flac"):
                filepath = os.path.join(root, file)
                tags = get_tags(filepath)
                flacs.append((filepath, tags))
    return flacs

class FfmpegMetadata:
    def __init__(self):
        self.tags = []
    
    def add(self, key, value):
        if type(value) is list:
            value = ";".join(value)
        self.tags.append(f"{key.upper()}={value}")

    def to_metadata(self):
        out = []
        for tag in self.tags:
            out.append("-metadata")
            out.append(tag)
        return out                

def add_tags(directory, filepath, genres, date, tracknum, title):
    metadata_entries = FfmpegMetadata()
    if len(genres):
        metadata_entries.add("GENRE", genres)
    metadata_entries.add("DATE", date)
    metadata_entries.add("ORIGINALDATE", date)
    args = ["ffmpeg", "-i", f'{filepath}', *metadata_entries.to_metadata(), "-codec", "copy", 'output.flac']
    result = subprocess.run(args)
    if result.returncode == 0:
        shutil.move('output.flac', filepath)
        title = title.replace("/", "-")
        shutil.move(filepath, f"{directory}/{tracknum:0>2} - {title}.flac")
        return True
    print(result)
    return False

def get_api():
    data = request("https://music-api.girlypop.no/")
    if data.status == 200:
        return data.json()
    
def matches_album(album, artist, album_title):
    album_artists = [y["name"].lower() for y in album["artists"]]
    if album["title"].lower() != album_title.lower():
        return False
    if artist.lower() not in album_artists:
        return False
    print(album_artists)
    return True

def get_album(api_data, artist, album_title):
    album = [x for x in api_data if matches_album(x, artist, album_title)]
    if len(album) != 1:
        return None
    return album[0]
    
def set_permissions(path):
    for dirpath, dirnames, filenames in os.walk(path):
        os.chmod(dirpath, 0o775)
        shutil.chown(dirpath, 1026, 100)
        for filename in filenames:
            os.chmod(os.path.join(dirpath, filename), 0o775)
            shutil.chown(os.path.join(dirpath, filename), 1026, 100)


def main():
    zb = sys.stdin.buffer.read()
    zs = zb.decode("utf-8", "replace")
    inf = json.loads(zs)
    data = get_api()
	
    total_sz = 0
    for upload in inf:
        ap = upload["ap"]
        path = ap.rsplit("/",1)[0]
        extracted_path = path + "/uploaded/album" # hacky lol ()
        if ap.endswith(".zip"):
            with zipfile.ZipFile(ap, 'r') as zip_ref:
                zip_ref.extractall(extracted_path)
        files = [f for f in os.listdir(extracted_path) if os.path.isfile(os.path.join(extracted_path, f)) and f.endswith(".flac")]
        flacs = get_flacs(extracted_path)
        if len(flacs) > 0:
            _, first_tags = flacs[0]
            artist_name = get_tag(first_tags, "ARTIST").strip()
            album_name = get_tag(first_tags, "ALBUM").strip()
            album_artist_name = get_tag(first_tags, "ARTIST").strip()
            if not album_artist_name.startswith(artist_name):
                _, first_tags = flacs[-1]
                artist_name = get_tag(first_tags, "ARTIST").strip()
                album_name = get_tag(first_tags, "ALBUM").strip()
            album = get_album(data, artist_name, album_name)
            if album:
                should_continue = True
                for flac, tags in flacs:
                    tracknum = int(get_tag(tags, "track"))
                    track_title = get_tag(tags, "title")
                    should_continue = add_tags(extracted_path, flac, [x["name"] for x in album["genres"]], album["date"], tracknum, track_title)
                    if not should_continue:
                       exit()
        shutil.move(f"{path}/uploaded", f"{path}/{artist_name}")
        shutil.move(f"{path}/{artist_name}/album", f"{path}/{artist_name}/{album_name}")
        dest = f"/w/music/{artist_name}/{album_name}"
        if os.path.exists(dest):
        	shutil.rmtree(dest, ignore_errors=False)
        shutil.move(f"{path}/{artist_name}/{album_name}", dest)
        set_permissions(dest)
        os.rmdir(f"{path}/{artist_name}")
        os.remove(ap)


if __name__ == "__main__":
    main()
