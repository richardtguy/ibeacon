import sys, argparse
from jubilee import ibeacon

# parse command line argument for topic (--topic)
parser = argparse.ArgumentParser()
parser.add_argument("--topic", help="pub/sub topic for ibeacon adverts")
args = parser.parse_args()
if args.topic:
    scanner = ibeacon.Scanner(topic=args.topic)
else:
	scanner = ibeacon.Scanner()
scanner.scan_forever()