import ibeacon

scanner = ibeacon.Scanner(topic='ibeacon/abc12')
scanner.scan_forever()
