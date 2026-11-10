import urllib.request
import re

url = 'https://www.techopsexamples.com/p/aws-networking-basics-aws-subnets-for-beginners'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')

body = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
body = re.sub(r'<style.*?</style>', '', body, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', body)
text = ' '.join(text.split())
print("Text length:", len(text), flush=True)
print("Sample text:", text[:1000], flush=True)
