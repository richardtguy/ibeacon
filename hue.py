import requests, json, datetime
import log
import config

class DaylightSensor():
	"""
	Implement a daylight sensor. Query() method returns true if daylight, false if not
	"""
	
	def __init__(self, lat, lng):
		"""
		Initialise sensor
		"""
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

		if (time > self.daylight_times['sunrise']) and (time < self.daylight_times['sunset']):
			return True
		else:
			return False


class HueController():
	"""
	Implement a controller to initiate actions on hue bridge based on rules.
	Usage: call poll() method in a loop to check rules and take predefined actions.
	"""
	
	def __init__(self, bridge, rules, daylight_sensor):
		"""
		Initialise controller and read rules from file
		"""
		# set up log
		self.logger = log.TerminalLog()
		
		self.bridge = bridge
		self.daylight_sensor = daylight_sensor
		
		self.last_tick_daylight = False
		self.last_tick = datetime.datetime.now()

		# read rules from file
		with open(rules, 'r') as f:
			self.rules = json.loads(f.read())
		
		# change time strings to datetime objects for each rule
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
				if (self.last_tick < rule['time']) and (now > rule['time']):
					self._apply_action(rule)
		
		self.last_tick = now
	
	def _apply_action(self, rule):
		"""
		Apply triggered action to lights defined in rule (or all lights if none given)
		"""
		try:
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
			self.logger.success('Triggered action %s' % (rule))
		except TypeError:
			self.logger.err('Action failed %s' % (rule))

	def _update_times_to_today(self, today):
		"""
		Replace year, month, day with today's values, leaving time unchanged
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
		print('Initialising Hue bridge...')
		url = 'http://'+IP+'/api/'+username+'/lights'
		r = requests.get(url)
		if r.status_code == 200:
			HueBridge.log.success('hue bridge ready')
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
					
	def __iter__(self):
		# create a list of HueLight objects to iterate over by index
		self.lights_list = list(self.lights.values())
		self.num_lights = len(self.lights_list)
		self.counter = -1
		return self
	
	def __next__(self):
		self.counter = self.counter + 1
		if self.counter == self.num_lights:
			raise StopIteration
		return self.lights_list[self.counter]
	
	def get(self, name):
		"""
		Return named HueLight object
		"""
		return self.lights[name]
		
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
