"""Ask VirusTotal what antivirus programs make of an executable (spec DIST-009).

    python tools/virustotal.py dist/renpytesterw.exe dist/renpytester.exe

Sends each file to VirusTotal, waits for it to be looked at, and says which antivirus programs
called it harmful and what they called it. A file sent there is passed on to the makers of those
programs, so send only what is going to be released anyway.

Needs a VirusTotal API key, which is free and is on the profile page of a VirusTotal account. It is
read from the VIRUSTOTAL_API_KEY environment variable, or else from a line VIRUSTOTAL_API_KEY=...
in a file named .env at the root of the repository, which git ignores. Without a key nothing is
sent and the tool says so. The key is never printed.

What the antivirus programs say is reported and nothing more: the tool ends with 0 whatever they
say, because a wrong verdict is theirs to put right, and with 1 only when the question could not
be asked. A development tool: nothing of it is in the program or the executable.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://www.virustotal.com/api/v3"
PAGE = "https://www.virustotal.com/gui/file/%s"
KEY_NAME = "VIRUSTOTAL_API_KEY"
# Above this size a file is sent to an address that has to be asked for first.
DIRECT_LIMIT = 32 * 1024 ** 2
# A free key may ask four times a minute.
POLL_SECONDS = 20
WAIT_SECONDS = 15 * 60
FLAGGED = ("malicious", "suspicious")


class Failed(Exception):
    """The question could not be asked or was not answered."""


def key_from(env_file, environ=os.environ):
    """The API key: from the environment, or else from the .env file. None when there is none."""
    if environ.get(KEY_NAME, "").strip():
        return environ[KEY_NAME].strip()
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        name, found, value = line.strip().removeprefix("export ").partition("=")
        if found and name.strip() == KEY_NAME and value.strip().strip("\"'"):
            return value.strip().strip("\"'")
    return None


def form(file_name, data):
    """A file as the body of a form, and the content type that goes with it."""
    boundary = uuid.uuid4().hex
    head = "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n" % (boundary, file_name)
    head += "Content-Type: application/octet-stream\r\n\r\n"
    body = head.encode("utf-8") + data + ("\r\n--%s--\r\n" % boundary).encode("ascii")
    return body, "multipart/form-data; boundary=" + boundary


def ask(key, url, body=None, content_type=None):
    """One question to VirusTotal, and its answer. Waits and asks again when asked to slow down."""
    headers = {"x-apikey": key, "accept": "application/json"}
    if content_type:
        headers["content-type"] = content_type
    for _attempt in range(5):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=300) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(60)
                continue
            if error.code == 401:
                raise Failed("VirusTotal did not accept the API key.")
            raise Failed("VirusTotal answered %s to %s." % (error.code, url.split("?")[0]))
        except (urllib.error.URLError, TimeoutError) as error:
            raise Failed("VirusTotal could not be reached: %s" % error)
    raise Failed("VirusTotal kept asking to slow down; the key's allowance may be used up.")


def analyse(key, file):
    """Sends the file and returns what the antivirus programs said of it, when all have."""
    data = file.read_bytes()
    target = API + "/files"
    if len(data) > DIRECT_LIMIT:
        target = ask(key, API + "/files/upload_url")["data"]
    body, content_type = form(file.name, data)
    analysis = ask(key, target, body, content_type)["data"]["id"]
    waited = 0
    while waited < WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        attributes = ask(key, API + "/analyses/" + analysis)["data"]["attributes"]
        if attributes["status"] == "completed":
            return attributes["results"]
    raise Failed("VirusTotal had not finished with %s after %d minutes." % (file.name, WAIT_SECONDS // 60))


def verdicts(results):
    """How many antivirus programs gave a verdict, and what each of those that mistrust it said."""
    judged = [name for name, said in results.items() if said["category"] in FLAGGED + ("harmless", "undetected")]
    flagged = sorted(
        (name, said.get("result") or said["category"]) for name, said in results.items()
        if said["category"] in FLAGGED)
    return len(judged), flagged


def report(file, digest, results):
    """What is said of one file, as lines for the terminal and for the page of a GitHub run."""
    judged, flagged = verdicts(results)
    lines = ["%s: %d of %d antivirus programs call it harmful." % (file.name, len(flagged), judged)]
    lines += ["  %s: %s" % pair for pair in flagged]
    lines += ["  " + PAGE % digest]
    page = ["**`%s`**: %d of %d antivirus programs call it harmful ([VirusTotal](%s))." % (
        file.name, len(flagged), judged, PAGE % digest), ""]
    page += ["- %s: `%s`" % pair for pair in flagged]
    return lines, page + [""]


def summarise(page):
    """On GitHub, puts what was found on the page of the run."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as out:
            out.write("### VirusTotal\n\n" + "\n".join(page) + "\n")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="the executables to ask about")
    args = parser.parse_args(argv)
    missing = [str(file) for file in args.files if not file.is_file()]
    if missing:
        print("No such file: %s" % ", ".join(missing))
        return 1
    key = key_from(ROOT / ".env")
    if key is None:
        print("Nothing was sent to VirusTotal: there is no %s in the environment or in .env." % KEY_NAME)
        summarise(["Not asked: the repository has no `%s` secret." % KEY_NAME])
        return 0
    page = []
    try:
        for file in args.files:
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            print("Sending %s (%s)..." % (file.name, digest), flush=True)
            lines, part = report(file, digest, analyse(key, file))
            print("\n".join(lines), flush=True)
            page += part
    except Failed as error:
        print(str(error))
        summarise(page + ["**Not finished:** %s" % error])
        return 1
    summarise(page)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
