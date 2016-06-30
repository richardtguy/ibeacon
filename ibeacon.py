import datetime, requests, json, subprocess, os
import config

def log(message, file):
	with open(file, 'a') as f:
		f.write('%s: %s\n' % (datetime.datetime.now(), message))
		if config.DEBUG: print(message)


class PresenceMonitor():
	"""
	Monitor whether house is occupied using iBeacons
	"""

	def __init__(self):
		"""
		Initialise PresenceMonitor
		"""
		self.beacons = {}
		

	def occupied(self):
		"""
		Return True if one or more registered iBeacons detected, False if none
		"""
		# run bash script to catch ibeacon advertisements until all registered beacons are
		# accounted for or a timeout is reached

		# start subprocesses (suppress broken pipe errors by redirecting to /dev/null)
		if not config.TESTING:
			hcidump_args = ['hcidump', '--raw', '-i', config.HCI]
		else:
			hcidump_args = ['cat', 'hcidump.dump']	
		parse_args = ['./ibeacon_parse.sh']
		hcidump_p = subprocess.Popen(hcidump_args, stdout=subprocess.PIPE)
		parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stdin=hcidump_p.stdout, stderr=config.DEVNULL)

		# initialise flags
		timed_out = False
		beacons_found = 0
		for b in self.beacons.keys(): self.beacons[b] = False
		start = datetime.datetime.now()
		
		while (not timed_out) & (beacons_found < len(self.beacons)):
			try:
				# read next line of output from subprocess
				beacon = json.loads(parse_p.stdout.readline())
				# if beacon is registered then log it as present
				if (beacon['Minor'] in self.beacons.keys()) and (self.beacons[beacon['Minor']] == False):
					if config.DEBUG: log('Found beacon: UUID: %s, Major: %s, Minor: %s, RSSI: %s' % (beacon['UUID'], beacon['Major'], beacon['Minor'], beacon['RSSI']), config.LOGFILE)
					self.beacons[beacon['Minor']] = True
					beacons_found += 1
			except ValueError as err:
				log('Warning: Could not parse bluetooth packets', config.LOGFILE)
				print(err)
				break

			# check for timeout
			elapsed_time = datetime.datetime.now() - start
			elapsed_secs = elapsed_time.seconds
			if elapsed_secs > config.SCAN_TIMEOUT:
				timed_out = True
	
		# terminate subprocesses
		parse_p.terminate()
		hcidump_p.terminate()

		# update whether house is occupied or not and return
		occupied = False
		for b in self.beacons.values():
			if b == True:
				occupied = True
				break

		return occupied
		
	def register_beacon(self, beacon):
		"""
		Add iBeacon to list of registered beacons
		"""
		self.beacons[beacon] = False
	
	def deregister_beacon(self, beacon):
		"""
		Remove iBeacon from list of registered beacons
		"""
		del self.beacons[beacon]

