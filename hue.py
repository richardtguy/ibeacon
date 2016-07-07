import requests, json, datetime, calendar, subprocess, signal
import log
import config

class ScanTimeout():
	"""
	Implement a timeout alarm
	"""
	def __init__(self, seconds=1, error_message='Timed out'):
		self.seconds = seconds
		self.error_message = error_message
		
	def _handle_timeout(self, signum, frame):
		raise ScanTimeoutError(self.error_message)
		
	def __enter__(self):
		signal.signal(signal.SIGALRM, self._handle_timeout)
		signal.alarm(self.seconds)
		
	def __exit__(self, type, value, traceback):
		signal.alarm(0)

class ScanTimeoutError(Exception):
	"""
	Exception handler for scan timeout
	"""
	def __init__(self, error_message):
		self.error_message = error_message
	
	def __str__(self):
		return repr(self.error_message)
		
class PresenceSensor():
	"""
	Implement a sensor to monitor if house is occupied using iBeacon key fobs
	occupied() method returns True if one or more registered beacons is found
	"""

	def __init__(self):
		"""
		Initialise PresenceMonitor
		"""
		self.beacons = {}
		
		# start scanning for bluetooth packets in subprocess
		subprocess.Popen(['sudo', 'hcitool', '-i', config.HCI, 'lescan', '--duplicates'], stdout=config.DEVNULL)

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
		
		while (not timed_out) and (beacons_found < 1):
			# read next line of output from subprocess
			with ScanTimeout(seconds=config.SCAN_TIMEOUT, error_message='no beacons found'):
				try:				
					# read next ibeacon advertisement packet
					beacon = json.loads(parse_p.stdout.readline())
					
					# if beacon is registered then log it as present
					if (beacon['Minor'] in self.beacons.keys()) and (self.beacons[beacon['Minor']] == False):
						if config.DEBUG: print('Found beacon: UUID: %s, Major: %s, Minor: %s, RSSI: %s' % (beacon['UUID'], beacon['Major'], beacon['Minor'], beacon['RSSI']))
						self.beacons[beacon['Minor']] = True
						beacons_found += 1
												
				except ScanTimeoutError as err:
					if config.DEBUG: print('Scan timed out; %s' % (err.error_message))

			# check for timeout
			elapsed_time = datetime.datetime.now() - start
			elapsed_secs = elapsed_time.seconds
			if elapsed_secs >= config.SCAN_TIMEOUT:
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

class DaylightSensor():
	"""
	Implement a daylight sensor
	query() method returns true if daylight, false if not
	"""
	
	def __init__(self, lat, lng):
		"""
		Initialise sensor
		"""
		# set up log
		self.logger = log.TerminalLog()
		
		self.update_daylight_due = datetime.datetime.now() + datetime.timedelta(hours=24)
		self.lat = lat
		self.lng = lng

		# initialise sunrise & sunset times
		now = datetime.datetime.now()
		self.daylight_times = self._get_daylight_times(now)
		self.logger.success('New daylight times (UTC) (sunrise: %s, sunset: %s)' % (self.daylight_times['sunrise'], self.daylight_times['sunset']))

	def _get_daylight_times(self, date):
		"""
		Return sunrise and sunset times from sunrise-sunset.org as datetime objects
		"""
		payload = {'lat': self.lat, 'lng': self.lng, 'date': date.isoformat()}
		r = requests.get('http://api.sunrise-sunset.org/json', params=payload)
		sunrise_str = r.json()['results']['sunrise']
		sunset_str = r.json()['results']['sunset']
			
		sunrise = datetime.datetime.strptime(sunrise_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)
		sunset = datetime.datetime.strptime(sunset_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)

		return {'sunrise': sunrise, 'sunset': sunset}
		
	def query(self, time):
		"""
		Return True if in daylight hours, False if not
		"""
		# update daylight times if >24 hours old
		if time > self.update_daylight_due:
			self.daylight_times = self._get_daylight_times(time)
			self.update_daylight_due = time
		
		# ensure daylight times are same day as query time		
		sunrise = self.daylight_times['sunrise'].replace(time.year, time.month, time.day)
		sunset = self.daylight_times['sunset'].replace(time.year, time.month, time.day)
		
		if (time > sunrise) and (time < sunset):
			return True
		else:
			return False

class UKTimeZone(datetime.tzinfo):
	"""
	Support conversion between local UK time and UTC.
	British Summer Time (BST) begins at 01:00 GMT on the last Sunday of March and ends at 01:00 GMT 
	(02:00 BST) on the last Sunday of October.  Local UK time is one hour ahead of UTC during BST and 
	equal to UTC outside BST.
	"""
	def __init__(self):
		# UTC offset outside British Summer Time (BST)
		self.__OFFSET = datetime.timedelta(0)

	def tzname(dt):
		"""
		Return name of time zone ('Europe/London')
		"""
		return 'Europe/London'

	def utcoffset(self, dt):
		"""
		Return offset between UTC and local time in UK (at time supplied as argument) in minutes east of UTC
		"""
		return self.__OFFSET + self.dst(dt)
		
	def dst(self, dt):
		"""
		Return Daylight Savings Time (DST) adjustment in minutes east of UTC
		"""
		# get start and end of Daylight Savings Time
		year = dt.year
		last_sunday_mar = max(week[-1] for week in calendar.monthcalendar(year, 3))
		last_sunday_oct = max(week[-1] for week in calendar.monthcalendar(year, 10))

		DST_START = datetime.datetime(year=year, month=3, day=last_sunday_mar, hour=1)
		DST_END = datetime.datetime(year=year, month=10, day=last_sunday_mar, hour=1)
		
		DST_OFFSET = -60

		if DST_START <= dt < DST_END:
			return datetime.timedelta(minutes=DST_OFFSET)
		else:
			return datetime.timedelta(0)


class HueController():
	"""
	Implement a controller to initiate actions on hue bridge based on time-based rules
	Usage: call tick() method in a loop to check rules and take predefined actions
	"""
	
	def __init__(self, bridge, rules, daylight_sensor, presence_sensor=None):
		"""
		Initialise controller and read rules from file
		"""
		# set up log
		self.logger = log.TerminalLog()
		
		# UK time zone object
		self.tz = UKTimeZone()
		
		if isinstance(bridge, HueBridge):
			self.bridge = bridge
		else:
			self.logger.err('Invalid HueBridge object %s supplied to HueController %s' % (bridge, self))
		if isinstance(daylight_sensor, DaylightSensor):
			self.daylight_sensor = daylight_sensor
		else:
			self.logger.err('Invalid DaylightSensor object %s supplied to HueController %s' % (daylight_sensor, self))
		if (presence_sensor != None) and (isinstance(presence_sensor, PresenceSensor)):
			self.presence_sensor = presence_sensor
		else:
			self.logger.err('Invalid PresenceMonitor object %s supplied to HueController %s' % (presence_sensor, self))
					
		self.last_tick_daylight = False
		self.last_tick = datetime.datetime.now()

		# read rules from file
		with open(rules, 'r') as f:
			self.rules = json.loads(f.read())
		
		# change time strings in each rule to datetime objects
		for rule in self.rules.values():
			try:
				rule['time'] = datetime.datetime.strptime(rule['time'],'%H:%M')
			except:
				if (rule['time'] != 'sunrise') and (rule['time'] != 'sunset'):
					raise ValueError
		
	def tick(self):
		"""
		Check rules and trigger predefined actions
		"""
		# timer
		now = datetime.datetime.now()
		# daylight sensor
		daylight = self.daylight_sensor.query(now)

		# update trigger times to today before checking against time now
		self._update_times_to_today(now)		

		# run rules
		for rule in self.rules.values():
			# daylight rules
			if (rule['trigger'] == 'daylight'):
				if self.last_tick_daylight != daylight:
					if (rule['time'] == 'sunset') and not daylight:
						self._apply_action(rule)
					if (rule['time'] == 'sunrise') and daylight:
						self._apply_action(rule)
			# timer rules
			else:
				if (self.last_tick < rule['time'] + self.tz.utcoffset(rule['time'])) and (now > rule['time']  + self.tz.utcoffset(rule['time'])):
					self._apply_action(rule)
		
		self.last_tick = now
		self.last_tick_daylight = daylight
	
	def _apply_action(self, rule):
		"""
		Apply triggered action to lights defined in rule (or all lights if none given)
		"""
		try:
			self.logger.success('Triggered action %s' % (rule))
			if rule['action'] == 'on':
				if len(rule['lights']) == 0:
					for light in self.bridge:
						light.on()
				else:
					for light in rule['lights']:
						self.bridge.get(light).on()
			if rule['action'] == 'off':
				if len(rule['lights']) == 0:
					for light in self.bridge:
						light.off()		
				else:
					for light in rule['lights']:
						self.bridge.get(light).off()
			if rule['action'] == 'scene':
				self.bridge.recall_scene(rule['scene'])
		except TypeError:
			self.logger.err('Action failed %s' % (rule))
			
		# turn all lights off again if no-one is home
		if self.presence_sensor != None:
			if not self.presence_sensor.occupied():
				self.logger.info('There\'s no-one home; switching lights off')
				for light in self.bridge:
					light.off()

	def _update_times_to_today(self, today):
		"""
		Replace year, month, day with today's values, and adjust to UTC
		"""
		date = datetime.datetime.today()
		for rule in self.rules.values():
			if (rule['time'] != 'sunrise') and (rule['time'] != 'sunset'):
				rule['time'] = rule['time'].replace(date.year, date.month, date.day)

class HueBridge():
	"""
	Implement a simplified API for a Philips hue bridge.
	Iterating over HueBridge returns each HueLight object
	"""

	# set up log
	log = log.TerminalLog()

	def __init__(self, username, IP):
		"""
		Query hue bridge using given username and IP address to get list
		of lights. Create a dictionary containing HueLight object for
		each light, with names as keys
		"""
		self.username = username
		self.IP = IP
		
		url = 'http://'+self.IP+'/api/'+self.username+'/lights'
		r = requests.get(url)
		if r.status_code == 200:
			HueBridge.log.success('Hue bridge ready')
		else:
			HueBridge.log.err('Could not contact hue bridge')
		r = r.json()
	
		self.lights = {}	
		for light_id in r:
			name = (r[light_id]['name'])
			self.lights[name] = HueLight(name,light_id)

		# set username and IP address for all HueLight objects
		HueLight.username = username
		HueLight.IP = IP

		if config.DEBUG:
			for light in self:
				HueBridge.log.success(light.get_name())
					
	def __iter__(self):
		# create a list of HueLight objects to iterate over by index
		self.lights_list = list(self.lights.values())
		self.num_lights = len(self.lights_list)
		self.counter = -1
		return self
	
	def next(self):
		self.counter = self.counter + 1
		if self.counter == self.num_lights:
			raise StopIteration
		return self.lights_list[self.counter]
	
	def get(self, name):
		"""
		Return named HueLight object
		"""
		return self.lights[name]
		
	def recall_scene(self, scene):
		"""
		Recall a scene by id from the bridge; current lamp on/off states are preserved.
		"""
		# store current on/off states of lamps
		for light in self.lights.values():
			light.save_state()
		
		# recall named scene
		url = 'http://'+self.IP+'/api/'+self.username+'/groups/0/action'
		payload = '{"scene":"'+scene+'"}'
		r = requests.put(url, data=payload)
		if r.status_code == 200:
			HueBridge.log.success('Recalled scene: ' + scene)
		else:
			HueBridge.log.err('Failed to recall scene: ' + scene)

		# restore previous on/off states		
		for light in self.lights.values():
			if light.state['on']: light.on()
			else: light.off()

		return r.json()	
		
class HueLight():
	"""
	Implement a simplified API for a Philips hue light
	"""
	username = ''
	IP = ''
	
	def __init__(self, name, ID):
		self.name = name
		self.ID = ID
		
	def get_name(self):
		"""
		Return the name of the light
		"""
		return self.name
		
	def on(self):
		"""
		Switch the light on
		"""
		self.__on_or_off('on')
	
	def off(self):
		"""
		Switches the light off
		"""
		self.__on_or_off('off')
		
	def __on_or_off(self, operation):
		url = 'http://'+self.IP+'/api/'+self.username+'/lights/'+self.ID+'/state'
		if operation == 'on':
			payload = '{"on": true}'
		else:
			payload = '{"on": false}'
		r = requests.put(url, data=payload)
		if r.status_code == 200:
			HueBridge.log.success(self.name + ' ' + operation)
		else:
			HueBridge.log.err(self.name + ' ' + operation)
		return r.json()
		
	def save_state(self):
		"""
		Fetch current state of light from bridge and save
		"""
		url = 'http://'+self.IP+'/api/'+self.username+'/lights/'+self.ID
		r = requests.get(url)
		self.state = r.json()['state']
		return self.state		
