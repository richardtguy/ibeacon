import requests, json, datetime, calendar, subprocess, signal, time, random, os
import log
import config

__version__ = '1.2.0'

"""
Bridge and HueLight objects are not threadsafe, so use locks to ensure only one process
can access these at a time (e.g. when iterating over the bridge).
v1.2.0  Added support for Lightify Gateway
v1.1.1	Added option to filter rules by days of the week
v1.1.0	Added HueController & DaylightSensor classes
v1.0.0	HueLight & Bridge classes
"""

LIGHTIFY_SESSION_TIMEOUT = 14

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


class Controller():
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
		
		if isinstance(bridge, Bridge):
			self.bridge = bridge
		else:
			self.logger.err('Invalid Bridge object %s supplied to HueController %s' % (bridge, self))
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

class Bridge():
	"""
	Implement a simplified API for a Philips Hue bridge and/or Osram Lightify Gateway.
	Iterating over Bridge returns each HueLight or LightifyLight object
	Documentation:
		Lightify Cloud API - https://eu.lightify-api.org/
		Philips Hue API - http://www.developers.meethue.com/philips-hue-api
	"""
	# set up log
	log = log.TerminalLog()

	def __init__(self, hue_uname=None, hue_IP=None, lightify_uname=None, lightify_pword=None, lightify_serial=None):

		# read list of connected lights from file if available, or connect to bridge and gateway to rebuild list
		self.lights = {}
		fname = 'saved_lights.json'
		try:
			# read list of lights from file and write to self.lights
			with open(fname, 'r') as f:
				saved_lights = json.load(f)
			print('Retrieving saved list of lights...')
			for l in saved_lights:
				if l['type'] == 'Hue':
					self.lights[l['name']] = HueLight(l['name'], l['id'], l['uid'])
				elif l['type'] == 'Lightify':
					self.lights[l['name']] = LightifyLight(l['name'], l['id'], l['uid'])
				Bridge.log.success(self.get(l['name']).get_name())

		except IOError:
			# if saved list of lights does not exist then rebuild it
			print('Unable to read saved list of lights, attempting to rebuild.')
			# connect to Philips Hue bridge and load connected lights (if applicable)
			if hue_uname != None:
				print('Connecting to Hue Bridge...')
				self._connect_to_hue_bridge(hue_uname, hue_IP)
		
			# connect to Osram Lightify gateway and load connected lights (if applicable)
			if lightify_uname != None:
				print('Connecting to Lightify Gateway...')
				self._connect_to_lightify_gateway(lightify_uname, lightify_pword, lightify_serial)

			# save list of lights to file
			lights_to_save = []
			for name, obj in self.lights.items():
				if isinstance(obj, HueLight):
					type = 'Hue'
				elif isinstance(obj, LightifyLight):
					type = 'Lightify'
				light = {'type':type, 'name':name, 'id':obj.ID, 'uid':obj.UID}
				lights_to_save.append(light)
			with open(fname, 'w') as f:
				json.dump(lights_to_save, f)
			# delete old saved scenes (as the lights will have inconsistent UIDs)
			try:
				os.remove('saved_scenes.json')
			except IOError:
				pass	
		
		# read saved scenes from file
		print('Loading saved scenes...')
		try:
			with open('saved_scenes.json', 'r') as f:
				self.scenes = json.load(f)
		except IOError:
			self.scenes = {}
		
	def _connect_to_hue_bridge(self, username, IP):
		"""
		Query hue bridge using given username and IP address to get list
		of lights. Create a HueLight object for each light, with names as keys
		and append to lights dictionary.
		"""
		self.hue_uname = username
		self.hue_IP = IP
		
		url = 'http://'+self.hue_IP+'/api/'+self.hue_uname+'/lights'
		r = requests.get(url)
		if r.status_code == 200:
			Bridge.log.success('Hue bridge ready')
		else:
			Bridge.log.err('Could not contact hue bridge')
		r = r.json()
	
		for light_id in r:
			name = (r[light_id]['name'])
			self.lights[name] = HueLight(name,light_id)

		# set username and IP address for all HueLight objects
		HueLight.username = username
		HueLight.IP = IP

		for light in self:
			Bridge.log.success(light.get_name())

	def _connect_to_lightify_gateway(self, lightify_uname, lightify_pword, lightify_serial):
		"""
		Query Lightify gateway using given username, password and IP address to get list
		of lights. Create and initialise a LightifyLight object for each light, with names 
		as keys and append to lights dictionary.
		"""
		API = LightifyLight.API
		
		# start session (use username, password and gateway serial number to get security token & user ID)
		url = API+'/session'
		headers = {'Content-Type': 'application/json'}
		payload = {'username': lightify_uname, 'password': lightify_pword, 'serialNumber': lightify_serial}
		r = requests.post(url, json=payload)
		if r.status_code == 200:
			Bridge.log.success('Connected to Lightify Gateway')
			LightifyLight.token_expiry = datetime.datetime.utcnow()
		else:
			Bridge.log.err('Could not contact Lightify Gateway (%s)' % (r.status_code))
		r = r.json()
		user_ID = r['userId']
		securityToken = r['securityToken']

		# query gateway for list of connected lights
		url = API+'/devices'
		headers = {'Content-Type': 'application/json', 'authorization':securityToken}
		r = requests.get(url, headers=headers)
		if r.status_code == 200:
			Bridge.log.success('List of lights received from Lightify Gateway')
		else:
			Bridge.log.err('Problem getting list of lights from Lightify Gateway')
		r = r.json()
		
		# create LightifyLight objects and append to lights list
		for light in r:
			name = light['name']
			ID = light['deviceId']
			self.lights[name] = LightifyLight(name, ID)

		# set username, password, IP address, gateway serial and initialise security token for all LightifyLight objects
		LightifyLight.uname = lightify_uname
		LightifyLight.pword = lightify_pword
		LightifyLight.serial = lightify_serial

		LightifyLight.token = securityToken
		LightifyLight.token_expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=LIGHTIFY_SESSION_TIMEOUT)

		for light in self:
			Bridge.log.success(light.get_name())

	
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

	def __next__(self):
		return self.next()

	def get(self, name):
		"""
		Return named light object
		"""
		return self.lights[name]

	def _get_by_UID(self, UID):
		"""
		Return light object with corresponding UID
		"""
		for light in self.lights.values():
			if light.UID == UID: return light
		raise KeyError('Light with specified UID not found')
	
	def save_scene_locally(self, scene_name):
		"""
		Save current lights settings as a new scene with a supplied name (must be unique)
		"""
		# save states of all lights
		scene = {}
		for light in self.lights.values():
			scene[light.UID] = light.save_state()
		self.scenes[scene_name] = scene
		with open('saved_scenes.json', 'w') as f:
			json.dump(self.scenes, f)
		Bridge.log.success('Saved scene: ' + scene_name)
		
	def recall_local_scene(self, scene_name):
		"""
		Recall saved light settings
		"""
		err = False

		# store current on/off states of lamps
		for light in self.lights.values():
			light.save_state()

		# recall states of all lights from saved scene
		try:
			scene = self.scenes[scene_name]
		except KeyError, OSError:
			Bridge.log.err('Scene not found: ' + scene_name)
			return
		for light_UID, light_state in scene.items():
			if self._get_by_UID(light_UID).recall_state(light_state) == 0: err = True
		if err:
			Bridge.log.err('Problem recalling scene: ' + scene_name)
		else:
			Bridge.log.success('Recalled scene: ' + scene_name)

		# restore previous on/off states		
		for light in self.lights.values():
			if light.state['on']: light.on()
			else: light.off()

	def recall_scene(self, scene):
		"""
		Recall a scene by id from the Hue bridge; current lamp on/off states are preserved.
		Lightify lights are unaffected.
		"""
		# store current on/off states of lamps
		for light in self.lights.values():
			light.save_state()
		
		# recall named scene
		url = 'http://'+self.IP+'/api/'+self.username+'/groups/0/action'
		payload = '{"scene":"'+scene+'"}'
		r = requests.put(url, data=payload)
		if r.status_code == 200:
			Bridge.log.success('Recalled scene: ' + scene)
		else:
			Bridge.log.err('Failed to recall scene: ' + scene)

		# restore previous on/off states		
		for light in self.lights.values():
			if light.state['on']: light.on()
			else: light.off()

		return r.json()

# helper function to generate random unique IDs 
def get_UID(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', length=8):
	ID = ''
	for c in range(length):
		rand_index = random.randrange(len(alphabet))
		char = alphabet[rand_index]
		ID = ID + char
	return ID

class HueLight():
	"""
	Implement a simplified API for a Philips hue light (on/off, save & recall state)
	"""
	username = ''
	IP = ''
	
	def __init__(self, name, ID, UID=None):
		# name as stored in Hue bridge
		self.name = name
		# light ID as stored in Hue bridge
		self.ID = ID
		# unique ID used to identify light in scenes (avoids problems if names are duplicated across Lightify gateway and Hue bridge)
		if UID == None:
			self.UID = get_UID
		else:
			self.UID = UID 
	
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
			Bridge.log.success(self.name + ' ' + operation)
		else:
			Bridge.log.err(self.name + ' ' + operation)

	def save_state(self):
		"""
		Fetch current state of light from bridge and save
		"""
		url = 'http://'+self.IP+'/api/'+self.username+'/lights/'+str(self.ID)
		r = requests.get(url)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			Bridge.log.err(self.name + 'Failed to save state')
			return 0
		self.state = r.json()['state']
		return self.state

	def recall_state(self, state):
		"""
		Set light to previously saved parameters (brightness, colour temperature/colour & on/off only)
		"""
		url = 'http://'+self.IP+'/api/'+self.username+'/lights/'+self.ID+'/state'
		try:
			if state['colourmode'] == 'hs':
				# set hue & saturation
				color_command = ',"hue":'+str(state['hue'])+',"sat":'+str(state['sat'])
			elif state['colourmode'] == 'xy':
				# set xy colour
				color_command = ',"xy":'+str(state['xy'])
			elif state['colourmode'] == 'ct':
				# set colour temperature
				color_command = ',"ct":'+str(state['ct'])
		except KeyError:
			# light doesn't support setting colour
			color_command = ''

		payload = '{"on":'+str(state['on'])+',"bri":'+str(state['bri'])+color_command+'}'
		r = requests.put(url, data=payload)
		if r.status_code == 200:
			return 1
		else:
			Bridge.log.err(self.name + ' ' + payload)
			return 0
	
class LightifyLight():
	"""
	Implement a simplified API for an Osram Lightify light (on/off, save & recall state)
	To Do: Streamline authentication as per http://docs.python-requests.org/en/master/user/advanced/#custom-authentication
	"""
	uname = config.LIGHTIFY_USERNAME
	pword = config.LIGHTIFY_PASSWORD
	serial = config.LIGHTIFY_SERIAL
	API = 'https://eu.lightify-api.org/lightify/services'
	token = ''
	token_expiry = datetime.datetime.utcnow()

	def __init__(self, name, ID, UID=None):
		# name as stored in Lightify gateway
		self.name = name
		# device ID as stored in Lightify gateway
		self.ID = ID
		# unique ID used to identify light in scenes (avoids problems if names are duplicated across Lightify gateway and Hue bridge)
		if UID == None:
			self.UID = get_UID()
		else:
			self.UID = UID

	def get_name(self):
		"""
		Return the name of the light
		"""
		return self.name

	def _get_security_token(self):
		if datetime.datetime.utcnow() > LightifyLight.token_expiry:
			url = LightifyLight.API+'/session'
			payload = {'username': LightifyLight.uname, 'password': LightifyLight.pword, 'serialNumber': LightifyLight.serial}
			r = requests.post(url, json=payload)
			if r.status_code != 200:
				Bridge.log.err('Could not get security token for Lightify gateway (%s)' % (r.status_code))
				return 0
			LightifyLight.token = r.json()['securityToken']
			LightifyLight.token_expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=LIGHTIFY_SESSION_TIMEOUT)
		return LightifyLight.token

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
		url = LightifyLight.API+'/device/set'
		if operation == 'on':
			payload = {'onoff': 1, 'idx': self.ID}
		else:
			payload = {'onoff': 0, 'idx': self.ID}		
		headers = {'Content-Type': 'application/json', 'authorization':self._get_security_token()}
		r = requests.get(url, headers=headers, params=payload)
		if r.status_code == 200:
			Bridge.log.success(self.name + ' ' + operation)
		elif r.status_code == 400:
			Bridge.log.err(self.name + ' ' + operation + ' (Invalid Security Token)')			
		else:
			Bridge.log.err(self.name + ' ' + operation)
		
	def save_state(self):
		"""
		Fetch current state of light from gateway and save
		"""
		url = LightifyLight.API+'/devices/'+str(self.ID)
		headers = {'Content-Type': 'application/json', 'authorization':self._get_security_token()}
		r = requests.get(url, headers=headers)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			Bridge.log.err(self.name + 'Failed to save state')
			return 0
		self.state = r.json()
		return self.state

	def recall_state(self, state):
		"""
		Set light to previously saved parameters (brightness, colour temperature & on/off only)
		Lightify API accepts on/off + brightness level or color temperature in one call, not all together
		"""
		url = LightifyLight.API+'/device/set'
		OK = True
				
		payload = {'idx': self.ID, 'onoff': state['on'], 'level': state['brightnessLevel']}
		headers = {'Content-Type': 'application/json', 'authorization':self._get_security_token()}
		r = requests.get(url, headers=headers, params=payload)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			Bridge.log.err(self.name + ' Failed to recall state')
			return 0
		
		payload = {'idx': self.ID, 'ctemp': state['temperature']}
		headers = {'Content-Type': 'application/json', 'authorization':self._get_security_token()}
		r = requests.get(url, headers=headers, params=payload)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			Bridge.log.err(self.name + ' Failed to recall state')
			return 0
		
		return 1