import requests, json, datetime, calendar, subprocess, signal
import log
import config

__version__ = '1.1.2'

"""
HueBridge and HueLight objects are not threadsafe, so use locks to ensure only one process
can access these at a time (e.g. when iterating over the bridge).
v1.1.1	Added option to filter rules by days of the week
v1.1.0	Added HueController & DaylightSensor classes
v1.0.0	HueLight & HueBridge classes
"""

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

	def _get_daylight_times(self, date):
		"""
		Return sunrise and sunset times from sunrise-sunset.org as datetime objects
		"""
		payload = {'lat': self.lat, 'lng': self.lng, 'date': date.isoformat()}
		try:
			r = requests.get('http://api.sunrise-sunset.org/json', params=payload, timeout=30)
			r.raise_for_status()
			sunrise_str = r.json()['results']['sunrise']
			sunset_str = r.json()['results']['sunset']
		except (requests.exceptions.HTTPError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as err:
			self.logger.warning("Failed to update daylight times! (%s)" % (err))
			return self.daylight_times
		sunrise = datetime.datetime.strptime(sunrise_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)
		sunset = datetime.datetime.strptime(sunset_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)
		self.logger.success('New daylight times (UTC) (sunrise: %s, sunset: %s), next update due at %s' % (sunrise, sunset, self.update_daylight_due))
		self.update_daylight_due = datetime.datetime.utcnow() + datetime.timedelta(hours=24)

		return {'sunrise': sunrise, 'sunset': sunset}
		
	def query(self, time=None):
		"""
		Return True if in daylight hours, False if not
		"""
		# set time to now if not supplied as argument
		if time is None:
			time = datetime.datetime.utcnow()
		
		# update daylight times if >24 hours old
		if time > self.update_daylight_due:
			self.daylight_times = self._get_daylight_times(time)
		
		# ensure daylight times are same day as query time		
		sunrise = self.daylight_times['sunrise'].replace(time.year, time.month, time.day)
		sunset = self.daylight_times['sunset'].replace(time.year, time.month, time.day)
		
		# return True if time is between sunrise and sunset, False otherwise
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
		if presence_sensor != None:
			self.presence_sensor = presence_sensor
		else:
			self.logger.err('Invalid PresenceMonitor object %s supplied to HueController %s' % (presence_sensor, self))
					
		self.last_tick_daylight = False
		self.last_tick = datetime.datetime.utcnow()

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
		
	def loop_once(self):
		"""
		Check rules and trigger predefined actions
		"""
		# timer
		now = datetime.datetime.utcnow()
		# daylight sensor
		daylight = self.daylight_sensor.query()

		# update trigger times to today before checking against time now
		self._update_times_to_today(now)		

		# run rules
		for rule in self.rules.values():
			# check rule applies today
			if self._check_weekday(rule):
				# daylight rules (triggered at sunrise or sunset)
				if (rule['trigger'] == 'daylight'):
					if self.last_tick_daylight != daylight:
						if (rule['time'] == 'sunset') and not daylight:
							self._apply_action(rule)
						if (rule['time'] == 'sunrise') and daylight:
							self._apply_action(rule)
				# timer rules (triggered at set times defined in local (UK) time)
				else:
					if (self.last_tick < rule['time'] + self.tz.utcoffset(rule['time'])) and (now > rule['time']  + self.tz.utcoffset(rule['time'])):
						self._apply_action(rule)
		
		self.last_tick = now
		self.last_tick_daylight = daylight

	def _check_weekday(self, rule, today=None):
		if today is None:
			today = datetime.datetime.today()
		try:
			if rule['days'][today.weekday()] == '1':
				return True
			else:
				return False
		except KeyError:
			return True
	
	def _apply_action(self, rule):
		"""
		Apply triggered action to lights defined in rule (or all lights if none given)
		"""
		try:
			self.logger.success('Triggered action %s at %s' % (rule, datetime.datetime.now().strftime('%a %d/%m/%Y %H:%M:%S')))
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
			if not self.presence_sensor.query():
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
