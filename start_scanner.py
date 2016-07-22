import ibeacon, config

scanner = ibeacon.Scanner(topic=config.TOPIC)
scanner.scan_forever()
