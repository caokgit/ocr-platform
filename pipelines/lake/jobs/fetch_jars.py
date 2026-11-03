"""Fetch the jars of jars.txt from Maven Central onto /data/jars, each checked against its published SHA-1;
skip a jar the Spark image already holds. Every job puts /data/jars/* on its driver's and executors' classpath
(docs/specs/data-path.md, row 15)."""

import hashlib
import os
import urllib.request

REPO = "https://repo1.maven.org/maven2"
DEST = "/data/jars"
image = os.listdir("/opt/spark/jars")
os.makedirs(DEST, exist_ok=True)
use = []
for line in open("/opt/lab/jars.txt"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    group, artifact, version = line.split(":")
    have = [j for j in image if j.startswith(artifact + "-") and j[len(artifact) + 1:len(artifact) + 2].isdigit()]
    if have:
        print(f"{artifact}: in the image ({have[0]}), skipped")
        continue
    name = f"{artifact}-{version}.jar"
    url = f"{REPO}/{group.replace('.', '/')}/{artifact}/{version}/{name}"
    path = os.path.join(DEST, name)
    want = urllib.request.urlopen(url + ".sha1").read().decode().split()[0]
    if not (os.path.exists(path) and hashlib.sha1(open(path, "rb").read()).hexdigest() == want):
        data = urllib.request.urlopen(url).read()
        got = hashlib.sha1(data).hexdigest()
        if got != want:
            raise SystemExit(f"{name}: sha1 {got}, Maven says {want}")
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
        print(f"{name}: fetched, {len(data):,} bytes, sha1 ok")
    else:
        print(f"{name}: already on the volume, sha1 ok")
    use.append(name)
extra = sorted(set(j for j in os.listdir(DEST) if j.endswith(".jar")) - set(use))
for j in extra:                       # a jar no longer listed must not stay on the classpath
    os.remove(os.path.join(DEST, j))
    print(f"{j}: no longer listed, removed")
print(f"{len(use)} jars on the volume: {', '.join(use)}")
