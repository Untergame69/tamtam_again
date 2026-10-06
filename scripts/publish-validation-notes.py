#!/usr/bin/env python3
"""Publish explicitly authorized change notes using the local YouTrack client."""
import argparse
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,"/home/Untergame/youtrack/scripts")
from youtrack_docs import YouTrackClient, YouTrackError, read_token

parser = argparse.ArgumentParser()
parser.add_argument("--apply",action="store_true")
args = parser.parse_args()
notes = json.loads((root/"docs/youtrack-validation-notes.json").read_text())
if not args.apply:
    print("Pending tickets: " + ", ".join(notes))
    sys.exit(0)
client = YouTrackClient("http://127.0.0.1:18080/work",read_token(Path("/home/Untergame/youtrack/secrets/docs-token.txt")))
try:
    for issue,text in notes.items():
        ticket = client.request("GET",f"/issues/{issue}",{"fields":"id,idReadable,summary"})
        comments = list(client.pages(f"/issues/{issue}/comments","id,text"))
        if not any(comment.get("text") == text for comment in comments):
            result = client.request("POST",f"/issues/{issue}/comments",{"fields":"id,text"},{"text":text})
            verification = client.request("GET",f"/issues/{issue}/comments/{result['id']}",{"fields":"id,text"})
            if verification.get("text") != text:
                raise YouTrackError("Published comment did not verify")
        print(issue + ": verified")
except YouTrackError as exc:
    print(str(exc),file=sys.stderr)
    sys.exit(2)
