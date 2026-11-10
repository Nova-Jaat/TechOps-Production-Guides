import urllib.request
import re

req = urllib.request.Request('https://lnkd.in/g7skN-bG', headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')

matches = re.findall(r'https?://[^\s"\'<>]+', content)
for m in set(matches):
    if 'licdn' not in m:
        print("URL:", m)
