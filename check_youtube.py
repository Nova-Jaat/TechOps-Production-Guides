import urllib.request
import re

articles = [
    'https://www.techopsexamples.com/p/aws-networking-basics-aws-subnets-for-beginners',
    'https://www.techopsexamples.com/p/how-to-automatically-block-suspicious-traffic-in-aws',
    'https://www.techopsexamples.com/p/how-aws-signed-urls-works-internally',
    'https://www.techopsexamples.com/p/designing-an-aws-machine-learning-architecture',
    'https://www.techopsexamples.com/p/how-aws-secures-inbound-and-outbound-network-traffic',
    'https://www.techopsexamples.com/p/how-to-design-a-secure-three-tier-architecture-on-aws',
    'https://www.techopsexamples.com/p/aws-internet-gateway-vs-nat-gateway-when-to-use-what',
    'https://www.techopsexamples.com/p/how-to-design-a-scalable-file-upload-architecture-in-aws',
    'https://www.techopsexamples.com/p/how-aws-lambda-prevents-function-throttling-during-traffic-spikes',
    'https://www.techopsexamples.com/p/using-cross-origin-resource-sharing-cors-in-amazon-s3'
]

for idx, url in enumerate(articles, 1):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        content = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')
        yt = re.findall(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s"\'<>]+', content)
        print(f"Article {idx}: {len(content)} bytes, YouTube links: {yt}")
    except Exception as e:
        print(f"Article {idx}: Error {e}")
