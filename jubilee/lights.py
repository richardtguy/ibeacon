# Built-in modules
import json, datetime, calendar, subprocess, signal, time, os, logging, threading, queue
import socket, binascii, struct

# Installed modules
import paho.mqtt.client as mqtt
import requests

# Package modules
from . import uid as uid_module

__version__ = '1.4.0'

"""
v1.4.0  Changed Bridge API to enable thread safety
v1.3.4	Consolidated modules into package 'jubilee'
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
	Sunrise and sunset times are retrieved for the specified location (lat/lon)
	If no location is supplied, attempts to find location from IP address using ipinfo.org
	query() method returns true if daylight, false if not
	"""
	
	def __init__(self, lat=None, lon=None):
		"""
		Initialise sensor
		"""		
		if (lat != None and lon != None):
			self.lat = lat
			self.lng = lon
		else:
			ipinfo = requests.get('https://ipinfo.io/geo').json()
			self.lat = ipinfo["loc"].split(',')[0]
			self.lng = ipinfo["loc"].split(',')[1]
		
		logger.debug('Daylight sensor initialised for latitude: %s, longitude: %s' % (self.lat, self.lng))

		# initialise sunrise & sunset times
		self.update_daylight_due = datetime.datetime.now() + datetime.timedelta(hours=24)
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
		DST_END = datetime.datetime(year=year, month=10, day=last_sunday_oct, hour=1)
		
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
					else:
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
		logger.info(("Remote connected to message broker with result code " + str(rc)))
		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		logger.info(('Subscribing to %s' % (self.topic)))
		self.mqttc.subscribe(self.topic)
		
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			logger.warning('Unexpected disconnection! (%s)' % (rc))
		logger.info('Remote disconnected from message broker')
		
	def _message_handler(self, client, userdata, message):
		# parse action from message
		msg = json.loads(message.payload.decode('utf-8'))
		logger.debug('Message received from broker: %s' % (msg))
		self.action_handler.apply_action(msg['action'])


class _ActionHandler():
	"""
	Parse and implement actions on behalf of Controller or Remote objects.
	Apply specified action to lights defined in rule (or all lights if none given)
	TO-DO: To ensure thread safety, only call methods on Bridge object, not lights
	"""
	def __init__(self, bridge):
		self.bridge = bridge
		
	def apply_action(self, rule):
		try:
			transition = rule['transition']
		except KeyError:
			transition = 4
		try:
			logger.info('Triggered action %s at %s' % (rule, datetime.datetime.now().strftime('%a %d/%m/%Y %H:%M:%S')))
			if rule['action'] == 'on':
				if len(rule['lights']) == 0:
					self.bridge.light_on([], transition=transition)
				else:
					for light in rule['lights']:
						self.bridge.light_on(light, transition=transition)
			if rule['action'] == 'off':
				if len(rule['lights']) == 0:
					self.bridge.light_off([], transition=transition)
				else:
					for light in rule['lights']:
						self.bridge.light_off(light, transition=transition)
			if rule['action'] == 'scene':
				self.bridge.recall_local_scene(rule['scene'], transition=transition)
		except TypeError:
			logger.error('Action failed %s' % (rule))
	

def sync(lock):
	def _function(f):
		def _wrapper(*args, **kargs):
			with lock: return f(*args, **kargs)
		return _wrapper
	return _function


class Bridge():
	"""
	Implement a simplified API for a Philips Hue bridge and/or Osram Lightify Gateway.
	Iterating over Bridge returns each _HueLight or _LightifyLight object
	Documentation:
		Lightify binary protocol - http://sarajarvi.org/lightify-haltuun/en.php
		Philips Hue API - http://www.developers.meethue.com/philips-hue-api
	"""

	lock = threading.Lock()

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
				if isinstance(obj, _HueLight):
					light = {'type':'Hue', 'name':name, 'id':obj.ID(), 'uid':obj.UID()}
				elif isinstance(obj, _LightifyLight):
					light = {'type':'Lightify', 'name':name, 'uid':obj.UID(), 'addr':obj.addr()}
				lights_to_save.append(light)
			with open(fname, 'w') as f:
				json.dump(lights_to_save, f, indent=4)
			# delete old saved scenes (as the lights will have inconsistent UIDs)
			try:
				os.remove('saved_scenes.json')
			except OSError:
				pass
		
		else:
			print('Retrieving saved list of lights... ', end='')
			for l in saved_lights:
				if l['type'] == 'Hue':
					# create _HueLight object with name, ID and UID from file
					self.lights[l['name']] = _HueLight(l['name'], l['id'], l['uid'], host=hue_IP, username=hue_uname)
					self.__hue_connected = True
					logger.info(self.lights[l['name']].name())
				elif l['type'] == 'Lightify':
					self.lights[l['name']] = _LightifyLight(l['addr'], lightify_IP, name=l['name'], uid=l['uid'])				
					self.__lightify_connected = True
					logger.info(self.lights[l['name']].name())
			print('OK')		
		
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
		of lights. Create a _HueLight object for each light, with names as keys
		and append to lights dictionary.
		"""
		self.__hue_connected = True
				
		url = 'http://'+IP+'/api/'+username+'/lights'
		r = requests.get(url)
		if r.status_code == 200:
			print('Hue bridge ready')
		else:
			print('Could not contact hue bridge')
		r = r.json()
	
		for light_id in r:
			name = (r[light_id]['name'])
			self.lights[name] = _HueLight(name,light_id, host=IP, username=username)
			print(self.lights[name].name())

	def _connect_to_lightify_gateway(self, hostname):
		"""
		Connect to Lightify gateway on local network, create a _LightifyLight object for
		each registered light, with names as keys and add to lights dictionary.
		"""
		# initialise connection to Lightify Gateway via local network
		self.__lightify_connected = True

		self.__lightify = LightifyGateway(hostname)
		self.__lightify.get_all_lights()

		for light in self.__lightify.lights.values():
			self.lights[light.name()] = light
			print(self.lights[light.name()].name())
	
	@sync(lock)
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
	
	@sync(lock)
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

	@sync(lock)
	def light_on(self, named_lights, transition=4):
		"""
		Switch on named light or lights (threadsafe)
		
		@param lights light or lights to switch as string or list of strings.
			Supply light name as string to switch one light.  
			Supply a list or tuple of light names to switch a group
			Supply empty list or tuple to switch all lights
		"""
		if isinstance(named_lights, (list, tuple)):
			if len(named_lights) == 0:
				named_lights = self.lights
		elif isinstance(named_lights, (str)):
			named_lights = [named_lights]
		else:
			raise TypeError('Invalid light name')
					
		for light in named_lights:
			self.lights[light].on(transition)						
	
	@sync(lock)
	def light_off(self, named_lights, transition=4):
		"""
		Switch off named light or lights (threadsafe)
		
		@param lights light or lights to switch as string or list of strings.
			Supply light name as string to switch one light.  
			Supply a list or tuple of light names to switch a group
			Supply empty list or tuple to switch all lights
		"""
		if isinstance(named_lights, (list, tuple)):
			if len(named_lights) == 0:
				named_lights = self.lights
		elif isinstance(named_lights, (str)):
			named_lights = [named_lights]
		else:
			raise TypeError('Invalid light name')
		
		for light in named_lights:
			self.lights[light].off(transition)


class _HueLight():
	"""
	Implement a simplified API for a Philips hue light (on/off, save & recall state)
	(direct calls to methods on _HueLight and _LightifyLight objects to be deprecated - 
	calls to methods on Bridge objects only preferred to enable implementation of thread 
	safety.)
	"""
	
	def __init__(self, name, ID, UID=None, host=None, username=None):
		# IP address for bridge and username
		self._IP = host
		self._username = username
		# name as stored in Hue bridge
		self.__name = name
		# light ID as stored in Hue bridge
		self.__ID = ID
		# unique ID used to identify light in scenes (avoids problems if names are duplicated across Lightify gateway and Hue bridge)
		if UID == None:
			self.__UID = uid_module.get_UID()
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
		url = 'http://'+self._IP+'/api/'+self._username+'/lights/'+self.__ID+'/state'
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
		logger.info('Getting current state of light %s' % (self.name()))		
		url = 'http://'+self._IP+'/api/'+self._username+'/lights/'+str(self.__ID)
		r = requests.get(url)
		try:
			r.raise_for_status()
		except requests.exceptions.HTTPError:
			logger.error(self.name() + 'Failed to save state')
			return 0
		state = r.json()['state']
		logger.debug('state: %s' % (state))
		return state

	def _recall_state(self, state, transition=4):
		"""
		Switch light on with previously saved parameters (brightness, colour temperature/colour & on/off only)
		"""
		url = 'http://'+self._IP+'/api/'+self._username+'/lights/'+self.__ID+'/state'
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

# binary commands for Lightify protocol
COMMAND_ALL_LIGHT_STATUS = 0x13
COMMAND_BRI = 0x31
COMMAND_ONOFF = 0x32
COMMAND_TEMP = 0x33
COMMAND_LIGHT_STATUS = 0x68

LIGHTIFY_PORT = 4000

class _Lightify():
	"""
	Base class with methods for communicating with Lightify Gateway
	"""
	def __init__(self, host, port=LIGHTIFY_PORT):
		self._host = host
		self._port = port		
	
	def _send_command(self, command):
		# create and connect a new socket, send command and receive response
		logger.debug('sending %s (%s bytes)' % (binascii.hexlify(command), len(command)))
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.connect((self._host, self._port))
			s.sendall(command)
			response = self._recv(s)
		return response

	def _recv(self, s):
		# receive response from gateway
		lengthsize = 2
		data = s.recv(lengthsize)
		(length,) = struct.unpack("<H", data[:lengthsize])
		chunks = []
		expected = length + 2 - len(data)
		while expected > 0:
			chunk = s.recv(expected)
			if chunk == b'':
				raise RuntimeError('socket connection broken')
			chunks.append(chunk)
			expected = expected - len(chunk)
		data = b''.join(chunks)
		logger.debug('received "%s" (%s bytes)' % (binascii.hexlify(data), len(data)))
		return data
	
class _LightifyLight(_Lightify):
	"""
	Implement an API for an Osram Lightify light (on/off, save & recall state).
	This object communicates with lights via a Lightify Gateway, using a binary protocol.
	"""			
	def __init__(self, addr, host, name=None, port=LIGHTIFY_PORT, uid=None):
		super(_LightifyLight, self).__init__(host, port)		
		self._addr = addr
		self._name = name
		# unique ID used to identify light in scenes (avoids problems if names are duplicated)
		if uid == None:
			self._UID = uid_module.get_UID()
		else:
			self._UID = uid
		self._state = self.save_state()

	def UID(self):
		"""
		Return the UID of the light
		"""
		return self._UID

	def name(self):
		"""
		Return the name of the light
		"""
		return self._name
		
	def addr(self):
		"""
		Return the name of the light
		"""
		return self._addr

	def on(self, transition=10):
		"""
		Switch the light on with previously saved settings
		"""
		if transition == False: transition = 10
		logger.info('Switching light %s on' % (self.name()))
		self._recall_state(self._state, transition=transition)
		
	def off(self, transition=10):
		"""
		Switch the light off
		"""
		if transition == False: transition = 10
		logger.info('Switching light %s off' % (self.name()))		
		self.set_bri(0, transition=transition)

	def save_state(self):		
		"""
		Return current state of light (query Gateway)
		"""
		logger.info('Getting current state of light %s' % (self.name()))	
		command = self._build_command(COMMAND_LIGHT_STATUS)
		while True:
			recvd_data = self._send_command(command)
			try:
				(on, bri, temp, r, g, b, h) = struct.unpack("<19x2BH4B3x", recvd_data)
			except(struct.error):
				logger.debug('Could not get state, trying again...')
				time.sleep(0.1)
			else:
				break
		state = {'on': on, 'bri': bri, 'temp': temp}
		logger.debug('state: %s' % (state))
		return state
	
	def _recall_state(self, state, transition=10):
		"""
		Switch on light to previously saved state
		"""
		logger.info('Recalling state: %s' % (state))
		# recall saved brightness & colour temperature
		self.set_bri(state['bri'], transition=transition)
		self.set_temp(state['temp'], transition=transition)

	def update_state(self, state):
		"""
		Update saved state
		"""
		self._state = state

	def set_bri(self, bri, transition=10):
		"""
		Set the brightness of the light
		"""
		logger.debug('Setting brightness of light %s to %s' % (self.name(), bri))		
		data = struct.pack("<BH",bri, transition)
		command = self._build_command(COMMAND_BRI, data=data)
		response = self._send_command(command)
		self._check_rc(response)

	def set_temp(self, temp, transition=10):
		"""
		Set the colour temperature of the light
		"""
		logger.debug('Setting temp of light %s to %s' % (self.name(), temp))		
		data = struct.pack("<HH", temp, transition)
		command = self._build_command(COMMAND_TEMP, data=data)
		response = self._send_command(command)
		self._check_rc(response)

	def _on_off(self, on_off):
		"""
		Switch the light on or off
		"""
		logger.debug('Switching light on to %s' % (self.name(), on_off))	
		data = struct.pack("<B",on_off)
		command = self._build_command(COMMAND_ONOFF, data=data)
		response = self._send_command(command)
		self._check_rc(response)

	def _build_command(self, command, data=b''):
		"""
		Build binary command to send to Gateway
		"""
		length = 14 + len(data)
		return struct.pack(
			"<H6BQ",
			length,
			0x00,
			command,
			0,
			0,
			0,
			0,
			self._addr
		) + data		

	def _check_rc(self, response):
		# seventh byte of response is a status code; 0 = success, 21 = addr not found	
		if response[6] == 0:
			logger.debug('OK')
		else:
			logger.warning('Operation failed (%s)' % (response[6]))	

class LightifyGateway(_Lightify):

	def get_all_lights(self):
		# query Gateway to get list of all lights with names and addresses
		self.lights = {}
		# build command to query Gateway for all light status
		command = self._build_global_command(COMMAND_ALL_LIGHT_STATUS, 1)
		# send command and receive response
		data = self._send_command(command)

		# get number of lights
		(num,) = struct.unpack("<H", data[7:9])
		logger.debug('num: %s' % (num))
		# parse status info for each light from response
		status_len = 50
		for i in range(0, num):
			pos = 9 + i * status_len
			payload = data[pos:pos+status_len]
			logger.debug("%s %s %s" % (i, pos, len(payload)))
			(a, addr, stat, name, extra) = struct.unpack("<HQ16s16sQ", payload)
			# Decode using cp437 for python3.
			name = name.decode('cp437').replace('\0', "")
			logger.info('light: %s %s %s %s' % (a, addr, name, extra))
			light = _LightifyLight(addr, self._host, name=name)
			self.lights[addr] = light		

	def _build_global_command(self, command, flag):
		length = 7
		result = struct.pack(
			"<H7B",
			length,
			0x02,
			command,
			0,
			0,
			0,
			0,
			flag
		)
		return result

