import urllib.request
import re

urls = [
  ('1: AWS Networking Basics', 'https://lnkd.in/g7skN-bG'),
  ('2: Block Suspicious Traffic', 'https://lnkd.in/ghrRnvDS'),
  ('3: AWS Signed URLs', 'https://lnkd.in/gVFj5C4x'),
  ('4: Machine Learning Architecture', 'https://lnkd.in/gmzHBV5J'),
  ('5: Secures Inbound Outbound', 'https://lnkd.in/gZDrHTbc'),
  ('6: Three Tier Architecture', 'https://lnkd.in/gHmPiwrB'),
  ('7: IGW vs NAT GW', 'https://lnkd.in/gv3XCgVi'),
  ('8: Scalable File Upload', 'https://lnkd.in/gYbWJ8UJ'),
  ('9: Lambda Function Throttling', 'https://lnkd.in/g63i6GK2'),
  ('10: S3 CORS', 'https://lnkd.in/gQDKH2ci')
]

for title, u in urls:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
        content = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
        matches = re.findall(r'https?://(?:www\.)?techopsexamples\.com/p/[^\s"\'<>]+', content)
        if matches:
            print(f"{title}: {matches[0]}")
        else:
            all_urls = [m for m in re.findall(r'https?://[^\s"\'<>]+', content) if 'linkedin.com' not in m and 'licdn' not in m]
            print(f"{title}: {all_urls}")
    except Exception as e:
        print(f"{title}: Error {e}")
