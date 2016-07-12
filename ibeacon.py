import paho.mqtt.client as mqtt
import config
import time, datetime, json, threading, os, subprocess

DEVNULL = open(os.devnull, 'wb')	# /dev/null



class Scanner():
	"""
	Scan for ibeacon avertisement packets and publish to MQTT message broker
	"""
	def __init__(self, IP='localhost', port='1883', hci='hci0'):
		# create and connect MQTT client object
		self.client = mqtt.Client()
		self.client.connect(IP, port=port)		
		self.hci = hci
		self.on = True
		
	def scan_forever(self):		
		# start scanning for bluetooth packets in subprocess
		subprocess.Popen(['sudo', 'hcitool', '-i', self.hci, 'lescan', '--duplicates'], stdout=DEVNULL)

		# start subprocesses in shell to dump and parse raw bluetooth packets
		hcidump_args = ['hcidump', '--raw', '-i', self.hci]
		parse_args = ['./ibeacon_parse.sh']
		hcidump_p = subprocess.Popen(hcidump_args, stdout=subprocess.PIPE)
		parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stdin=hcidump_p.stdout, stderr=DEVNULL)

		while self.on:
			# read next ibeacon advertisement packet (blocking if nothing to read)
			advert = parse_p.stdout.readline()
			print(advert)
			# publish ibeacon advertisment to MQTT broker
			self.client.publish("ibeacon/adverts", advert)


class PresenceSensor():
	"""
	Implement a sensor to monitor if house is occupied using iBeacon key fobs
	- An instance of Scanner object must be started with scan_forever() first to publish 
	  ibeacon advertisement packlets to MQTT message broker.
	- PresenceSensor then subscribes
	  to the topic ibeacon/adverts and keeps track of which beacons have been detected 
	  recently.
	- Callback functions may be set for last-one-out and first-one-in events.
	- PresenceSensor.query() method returns True if one or more registered beacons is 
	  found, false otherwise
	"""
	# define required iBeacon ID keys
	BEACON_ID_KEYS = ("UUID", "Major", "Minor")
	
	def __init__(self, first_one_in_callback=None, last_one_out_callback=None, IP='localhost', port='1883', scan_timeout=30):
		self.scan_timeout = scan_timeout
		self.registered_beacons = []		
		self.occupied = False

		# initialise MQTT client
		self.client = mqtt.Client()
		self.client.on_message = self._message_handler
		self.client.on_connect = self._on_connect
		self.client.on_disconnect = self._on_disconnect
		self.client.connect(IP, port=port)

		# set callback functions (if supplied as arguments)
		self.first_one_in_callback = first_one_in_callback
		self.last_one_out_callback = last_one_out_callback
	
	def _on_connect(self, client, userdata, flags, rc):
		print("Connected to message broker with result code " + str(rc))
		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		self.client.subscribe("ibeacon/adverts")
		
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			print('Unexpected disconnection!')
		print('Disconnected from message broker')		
	
	def register_beacon(self, beacon, owner):
		# add beacon to list of registered beacons
		for key in PresenceSensor.BEACON_ID_KEYS:
			if key not in beacon.keys(): 
				return "Failed to register beacon (missing or invalid ID)"
		if self._get_beacon(beacon) == None:
			self.registered_beacons.append({"owner": owner, "ID": beacon, "last_seen": datetime.datetime.now()})
			return "Registered beacon %s to owner %s" % (beacon, owner)

	def deregister_beacon(self, beacon):
		self.registered_beacons.remove(self._get_beacon(beacon))
		return "Deregistered beacon %s" % (beacon)

	def start(self):
		print("Starting Presence Sensor...")
		self.on = True
		# start non-blocking loop for presence sensor
		self.thread = threading.Thread(target=self._loop)
		self.thread.start()
	
	def stop(self):
		print("Stopping Presence Sensor...")
		self.on = False
		self.thread.join()
		# disconnect client object from MQTT server
		self.client.disconnect()
	
	def _loop(self):
		while self.on:
			# loop MQTT client (blocking) to periodically check for messages
			self.client.loop()	
			# if no registered_key_fobs seen for > SCAN_TIMEOUT then set occupied = False and call last_one_out_callback()
			now = datetime.datetime.now()
			beacons_found = 0
			for b in self.registered_beacons:
				if now - b['last_seen'] < self.scan_timeout:
					beacons_found += 1
			if (beacons_found == 0) and (self.occupied):
					self.occupied = False
					self.last_one_out_callback()

	def _message_handler(self, client, userdata, message):
		# parse beacon IDs from message and fetch beacon from registered list
		msg = json.loads(message.payload)
		beacon_ID = {}
		for key in PresenceSensor.BEACON_ID_KEYS:
			beacon_ID[key] = msg[key]
		beacon = self._get_beacon(beacon_ID)
		# if beacon is registered
		if (beacon != None):
			# update last seen datetime
			beacon['last_seen'] = datetime.datetime.now()
			if config.DEBUG: print("Beacon %s seen at %s" % (beacon['ID'], beacon['last_seen']))
			if self.occupied == False:
				self.occupied = True
				self.first_one_in_callback()

	def _get_beacon(self, beacon):
		for b in self.registered_beacons:
			if b['ID'] == beacon:
				return b
		return None

	def occupied(self):
		return self.occupied
		

"""
Dummy classes for offline development
"""

class DummyMessage():
	def __init__(self, payload):
		self.payload = payload
	
class DummyMQTTClient():
	def loop(self):
		time.sleep(1)
		message = DummyMessage('{"UUID": "aaa", "Major": "bbb", "Minor": "ccc", "RSSI": -27}')
		self.on_message(None, None, message)
		
	def loop_start(self):
		self.looping = True
		self.thread = threading.Thread(target=self._loop_forever)
		self.thread.start()
	
	def loop_stop(self):
		self.looping = False
		self.thread.join()
	
	def _loop_forever(self):
		while self.looping:
			self.loop()
			
	def connect(self, IP, port='1883'):
		self.on_connect(None, None, None, 0)
	
	def disconnect(self):
		pass
	
	def subscribe(self, topic):
		pass

