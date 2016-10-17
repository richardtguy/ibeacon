# Built-in modules
import json, datetime, calendar, subprocess, signal, time, os, logging
# Installed modules
import paho.mqtt.client as mqtt
import requests
# Local modules
import config, my_lightify, uid

__version__ = '1.3.3'

"""
Bridge and HueLight objects are not threadsafe, so use locks to ensure only one process
can access these at a time (e.g. when iterating over the bridge).
v1.3.3  Added remote control to apply actions via cloud MQTT
v1.3.2	Refactored lightify classes and moved into my_lightify.py
v1.3.1	Light states stored locally and recalled when light switched on
v1.3.0	Changed to control Lightify Gateway via LAN instead of Cloud API (for lower latency)
v1.2.0  Added support for Lightify Gateway (Cloud API)
v1.1.1	Added option to filter rules by days of the week
v1.1.0	Added HueController & DaylightSensor classes
v1.0.0	HueLight & Bridge classes
"""

logger = logging.getLogger(__name__)

class DaylightSensor():
	"""
	Implement a daylight sensor
	query() method returns true if daylight, false if not
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
		self.daylight_times = self._get_daylight_times(date=now)

	def query(self, time=None):
		"""
		Return True if in daylight hours, False if not
		"""
		# set time to now if not supplied as argument
		if time is None:
			time = datetime.datetime.utcnow()
		
		# update daylight times if >24 hours old
		if time > self.update_daylight_due:
			self.daylight_times = self._get_daylight_times(date=time)
		
		# ensure daylight times are same day as query time		
		sunrise = self.daylight_times['sunrise'].replace(time.year, time.month, time.day)
		sunset = self.daylight_times['sunset'].replace(time.year, time.month, time.day)
		
		# return True if time is between sunrise and sunset, False otherwise
		if (time > sunrise) and (time < sunset):
			return True
		else:
			return False

	def sunrise(self):
		"""
		Return stored sunrise time as datetime object
		"""
		# update daylight times if >24 hours old
		if datetime.datetime.utcnow() > self.update_daylight_due:
			self.daylight_times = self._get_daylight_times()
		# ensure daylight times are today
		today = datetime.datetime.today()	
		sunrise = self.daylight_times['sunrise'].replace(today.year, today.month, today.day)
		# return sunrise
		return sunrise

	def sunset(self):
		"""
		Return stored sunset time as datetime object
		"""
		# update daylight times if >24 hours old
		if datetime.datetime.utcnow() > self.update_daylight_due:
			self.daylight_times = self._get_daylight_times()
		# ensure daylight times are today
		today = datetime.datetime.today()	
		sunset = self.daylight_times['sunset'].replace(today.year, today.month, today.day)
		# return sunset
		return sunset

	def _get_daylight_times(self, date=None):
		"""
		Return sunrise and sunset times from sunrise-sunset.org as datetime objects
		"""
		logger.debug('Updating sunrise and sunset times...')
		if date is None:
			date = datetime.datetime.utcnow()
		payload = {'lat': self.lat, 'lng': self.lng, 'date': date.isoformat()}
		try:
			r = requests.get('http://api.sunrise-sunset.org/json', params=payload, timeout=30)
			r.raise_for_status()
			sunrise_str = r.json()['results']['sunrise']
			sunset_str = r.json()['results']['sunset']
		except (requests.exceptions.HTTPError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as err:
			logger.warning("Could not connect to sunrise-sunset.org (%s)" % (err))
			return self.daylight_times
		sunrise = datetime.datetime.strptime(sunrise_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)
		sunset = datetime.datetime.strptime(sunset_str,'%I:%M:%S %p').replace(date.year, date.month, date.day)
		logger.info('New daylight times (UTC) (sunrise: %s, sunset: %s), next update due at %s' % (sunrise, sunset, self.update_daylight_due))
		self.update_daylight_due = datetime.datetime.utcnow() + datetime.timedelta(hours=24)

		return {'sunrise': sunrise, 'sunset': sunset}


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
	Implement a controller to initiate actions on bridge based on time-based rules
	Usage: call tick() method in a loop to check rules and take predefined actions
	"""
	
	def __init__(self, bridge, rules, daylight_sensor, presence_sensor=None):
		"""
		Initialise controller and read rules from file
		"""
		# UK time zone object
		self.tz = UKTimeZone()
		
		if isinstance(bridge, Bridge):
			self.bridge = bridge
		else:
			logger.error('Invalid Bridge object %s supplied to HueController %s' % (bridge, self))
		if isinstance(daylight_sensor, DaylightSensor):
			self.daylight_sensor = daylight_sensor
		else:
			logger.error('Invalid DaylightSensor object %s supplied to HueController %s' % (daylight_sensor, self))
		if presence_sensor != None:
			self.presence_sensor = presence_sensor
		else:
			logger.error('Invalid PresenceMonitor object %s supplied to HueController %s' % (presence_sensor, self))

		self.last_tick_daylight = False
		self.last_tick = datetime.datetime.utcnow()

		# read rules from file
		with open(rules, 'r') as f:
			self.rules = json.loads(f.read())

		# set up handler to parse and implement actions
		self.action_handler = _ActionHandler(self.bridge)
		
		# change time strings in each rule to datetime objects
		for rule in self.rules:
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

		# update trigger times to today before checking against time now
		self._update_times_to_today(now)		

		# run rules
		for rule in self.rules:
			# check rule applies today
			if self._check_weekday(rule):

				# trigger time
				if (rule['trigger'] == 'daylight'):
					# daylight rules: set trigger time to sunrise/sunset +/- offset (UTC)
					if rule['time'] == 'sunrise':
						trigger_time = self.daylight_sensor.sunrise()
					elif rule['time'] == 'sunset':
						trigger_time = self.daylight_sensor.sunset()
					else:
						logger.error('Incorrect format for rule (%s)' % (rule))
					try:
						# add offset in minutes
						trigger_time += datetime.timedelta(minutes=rule['offset'])
					except KeyError:
						pass
				else:
					# timer rules: set trigger time to rule time adjusted to UTC
					trigger_time = rule['time'] + self.tz.utcoffset(rule['time'])

				# trigger rule if trigger_time has passed since last loop
				if (self.last_tick < trigger_time) and (now > trigger_time):
					# if using presence sensor, only apply on/off actions if at home
					if (self.presence_sensor != None):
						if (self.presence_sensor.query()) or (rule['action'] == 'scene'):
							self.action_handler.apply_action(rule)
		
		self.last_tick = now

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
	
	def _update_times_to_today(self, today):
		"""
		Replace year, month, day with today's values, and adjust to UTC
		"""
		date = datetime.datetime.today()
		for rule in self.rules:
			if (rule['time'] != 'sunrise') and (rule['time'] != 'sunset'):
				rule['time'] = rule['time'].replace(date.year, date.month, date.day)


class Remote():
	"""
	Connect to and initiate actions from client apps via cloud MQTT message broker
	"""
	def __init__(self, host, port, uname, pword, bridge, topic='lights'):
		# instance variables
		self.host = host
		self.port = port
		self.topic = topic
		self.bridge = bridge

		# initialise MQTT client
		self.mqttc = mqtt.Client()
		self.mqttc.on_connect = self._on_connect
		self.mqttc.on_disconnect = self._on_disconnect		
		self.mqttc.on_message = self._message_handler
		self.mqttc.username_pw_set(uname, password=pword)
		
		self.action_handler = _ActionHandler(self.bridge)

	def start(self):
		# connect to MQTT broker and listen (in new thread) for actions
		logger.info("Starting Remote...")
		self.mqttc.connect(self.host, port=self.port)
		# start threaded network loop
		self.mqttc.loop_start()
				
	def stop(self):
		logger.info("Stopping Remote...")
		# stop network loop
		self.mqttc.loop_stop()
		# disconnect client object from MQTT server
		self.mqttc.disconnect()
	
	def _on_connect(self, client, userdata, flags, rc):
		logger.info(("Presence Sensor connected to message broker with result code " + str(rc)))
		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		logger.info(('Subscribing to %s' % (self.topic)))
		self.mqttc.subscribe(self.topic)
		
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			logger.warning('Unexpected disconnection! (%s)' % (rc))
		logger.info('Presence Sensor disconnected from message broker')
		
	def _message_handler(self, client, userdata, message):
		# parse action from message
		msg = json.loads(message.payload.decode('utf-8'))
		logger.debug('Message received from broker: %s' % (msg))
		self.action_handler.apply_action(msg['action'])


class _ActionHandler():
	"""
	Parse and implement actions on behalf of Controller or Remote objects.
	Apply specified action to lights defined in rule (or all lights if none given)
	"""
	def __init__(self, bridge):
		self.bridge = bridge
		
	def apply_action(self, rule):
		try:
			transition = rule['transition']
		except KeyError:
			transition = False
		try:
			logger.info('Triggered action %s at %s' % (rule, datetime.datetime.now().strftime('%a %d/%m/%Y %H:%M:%S')))
			if rule['action'] == 'on':
				if len(rule['lights']) == 0:
					for light in self.bridge:
						light.on(transition=transition)
				else:
					for light in rule['lights']:
						self.bridge.get(light).on(transition=transition)
			if rule['action'] == 'off':
				if len(rule['lights']) == 0:
					for light in self.bridge:
						light.off(transition=transition)
				else:
					for light in rule['lights']:
						self.bridge.get(light).off(transition=transition)
			if rule['action'] == 'scene':
				self.bridge.recall_local_scene(rule['scene'])
		except TypeError:
			logger.error('Action failed %s' % (rule))
	

class Bridge():
	"""
	Implement a simplified API for a Philips Hue bridge and/or Osram Lightify Gateway.
	Iterating over Bridge returns each HueLight or LightifyLight object
	Documentation:
		Lightify Cloud API - https://eu.lightify-api.org/
		Philips Hue API - http://www.developers.meethue.com/philips-hue-api
	"""
	def __init__(self, hue_uname=None, hue_IP=None, lightify_IP=None):

		self.__hue_connected = False
		self.__lightify_connected = False
		
		# dict from light names to light objects
		self.lights = {}

		# read list of connected lights from file if available, or connect to bridge and gateway to rebuild list
		fname = 'saved_lights.json'
		try:
			# read list of lights from file and write to self.lights
			with open(fname, 'r') as f:
				saved_lights = json.load(f)
			print('Retrieving saved list of lights... ', end='')
			for l in saved_lights:
				if l['type'] == 'Hue':
					# create HueLight object with name, ID and UID from file
					self.lights[l['name']] = HueLight(l['name'], l['id'], l['uid'])
					self.__hue_connected = True
					logger.info(self.get(l['name']).name())
				elif l['type'] == 'Lightify':
					self.lights[l['name']] = my_lightify.LightifyLight(l['addr'], lightify_IP, name=l['name'], uid=l['uid'])				
					self.__lightify_connected = True
					logger.info(self.get(l['name']).name())
			print('OK')

		except IOError:
			# if saved list of lights does not exist then rebuild and save it
			print('Unable to read saved list of lights, attempting to rebuild...')
			# connect to Philips Hue bridge and load connected lights (if applicable)
			if hue_uname != None:
				print('Connecting to Hue Bridge...')
				self._connect_to_hue_bridge(hue_uname, hue_IP)
		
			# connect to Osram Lightify gateway and load connected lights (if applicable)
			if lightify_IP != None:
				print('Connecting to Lightify Gateway...')
				self._connect_to_lightify_gateway(lightify_IP)

			# save list of lights to file
			lights_to_save = []
			for name, obj in self.lights.items():
				if isinstance(obj, HueLight):
					light = {'type':'Hue', 'name':name, 'id':obj.ID(), 'uid':obj.UID()}
				elif isinstance(obj, my_lightify.LightifyLight):
					light = {'type':'Lightify', 'name':name, 'uid':obj.UID(), 'addr':obj.addr()}
				lights_to_save.append(light)
			with open(fname, 'w') as f:
				json.dump(lights_to_save, f, indent=4)
			# delete old saved scenes (as the lights will have inconsistent UIDs)
			try:
				os.remove('saved_scenes.json')
			except OSError:
				pass
		
		# read saved scenes from file
		print('Loading saved scenes... ', end='')
		try:
			with open('saved_scenes.json', 'r') as f:
				self.__scenes = json.load(f)
			print('OK')
		except IOError:
			print('No saved scenes found.')
			self.__scenes = {}
			
	def _connect_to_hue_bridge(self, username, IP):
		"""
		Query hue bridge using given username and IP address to get list
		of lights. Create a HueLight object for each light, with names as keys
		and append to lights dictionary.
		"""
		self.__hue_connected = True

		self.hue_uname = username
		self.hue_IP = IP
		
		url = 'http://'+self.hue_IP+'/api/'+self.hue_uname+'/lights'
		r = requests.get(url)
		if r.status_code == 200:
			print('Hue bridge ready')
		else:
			print('Could not contact hue bridge')
		r = r.json()
	
		for light_id in r:
			name = (r[light_id]['name'])
			self.lights[name] = HueLight(name,light_id)
			print(self.lights[name].name())

		# set username and IP address for all HueLight objects
		HueLight.username = username
		HueLight.IP = IP

	def _connect_to_lightify_gateway(self, hostname):
		"""
		Connect to Lightify gateway on local network, create a lightify.LightifyLight object for
		each registered light, with names as keys and add to lights dictionary.
		"""
		# initialise connection to Lightify Gateway via local network
		self.__lightify_connected = True

		self.__lightify = my_lightify.LightifyGateway(hostname)
		self.__lightify.get_all_lights()

		for light in self.__lightify.lights.values():
			self.lights[light.name()] = light
			print(self.lights[light.name()].name())
	
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
			if light.UID() == UID: return light
		raise KeyError('Light with specified UID not found')
	
	def save_scene_locally(self, scene_name):
		"""
		Save current lights settings as a new scene with a supplied name (must be unique)
		"""
		# save states of all lights
		scene = {}
		# save states of all lights
		for light in self.lights.values():
			scene[light.UID()] = light.save_state()
		self.__scenes[scene_name] = scene
		with open('saved_scenes.json', 'w') as f:
			json.dump(self.__scenes, f, indent=4)
		print('Saved scene: ' + scene_name)
		
	def recall_local_scene(self, scene_name, transition=4):
		"""
		Recall saved light settings
		"""

		# load light states corresponding to named scene
		try:
			scene = self.__scenes[scene_name]
		except (KeyError, OSError):
			logger.error('Scene not found: ' + scene_name)
			return

		# find saved state for each light in scene, update locally saved settings,
		# and push new settings to light if currently switched on
		for light in self.lights.values():
			for UID, light_state in scene.items():
				if UID == light.UID():
					if light.save_state()['on']:
						light._recall_state(light_state, transition=transition)
					light.update_state(light_state)

		
		logger.info('Recalled scene: ' + scene_name)
		

class HueLight():
	"""
	Implement a simplified API for a Philips hue light (on/off, save & recall state)
	"""
	username = config.HUE_USERNAME
	IP = config.HUE_IP_ADDRESS
	
	def __init__(self, name, ID, UID=None):
		# name as stored in Hue bridge
		self.__name = name
		# light ID as stored in Hue bridge
		self.__ID = ID
		# unique ID used to identify light in scenes (avoids problems if names are duplicated across Lightify gateway and Hue bridge)
		if UID == None:
			self.__UID = uid.get_UID()
		else:
			self.__UID = UID
		self.__state = self.save_state()

	def UID(self):
		return self.__UID
		
	def ID(self):
		return self.__ID
	
	def name(self):
		"""
		Return the name of the light
		"""
		return self.__name
		
	def on(self, transition=4):
		"""
		Switch the light on with previously saved settings
		"""
		if transition == False: transition = 4
		logger.info('Switching light %s on with saved settings' % (self.name()))
		self._recall_state(self.__state, transition=transition)

	def off(self, transition=4):
		"""
		Switches the light off
		"""
		if transition == False: transition = 4		
		self._on_or_off('off', transition)
		
	def _on_or_off(self, operation, transition):
		logger.info('Switching light %s %s' % (self.name(), operation))
		url = 'http://'+HueLight.IP+'/api/'+HueLight.username+'/lights/'+self.__ID+'/state'
		if operation == 'on':
			payload = {"on": True, "transitiontime":transition}
		else:
			payload = {"on": False, "transitiontime":transition}
		r = requests.put(url, json=payload)
		self._check_rc(r)
			
	def save_state(self):
		"""
		Fetch current state of light from bridge and save
		"""
		url = 'http://'+HueLight.IP+'/api/'+HueLight.username+'/lights/'+str(self.__ID)
		r = requests.get(url)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			logger.error(self.__name + 'Failed to save state')
			return 0
		state = r.json()['state']
		return state

	def _recall_state(self, state, transition=4):
		"""
		Switch light on with previously saved parameters (brightness, colour temperature/colour & on/off only)
		"""
		url = 'http://'+HueLight.IP+'/api/'+HueLight.username+'/lights/'+self.__ID+'/state'
		try:
			if state['colormode'] == 'hs':
				# set hue & saturation
				color_command = {"hue": state['hue'], "sat": state['sat']}
			elif state['colormode'] == 'xy':
				# set xy colour
				color_command = {"xy": state['xy']}
			elif state['colormode'] == 'ct':
				# set colour temperature
				color_command = {"ct": state['ct']}
		except KeyError:
			# light doesn't support setting colour
			color_command = ''

		payload = {"on":True,"bri":state['bri'],"transitiontime":transition}
		payload.update(color_command)
		r = requests.put(url, json=payload)
		self._check_rc(r)

	def update_state(self, state):
		# update saved parameters
		self.__state = state
		
	def _check_rc(self, r):
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			logger.warning('HTTP status: %s (%s)' % (r.text))
		else:
			for rc in r.json():
				if 'success' in rc:
					logger.debug(rc)
				else:
					logger.warning(rc)
