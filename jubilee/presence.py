# Built-in modules
import time
import datetime
import json
import threading
import os
import signal
import sys
import subprocess
import logging

# Installed modules
import paho.mqtt.client as mqtt

# Package modules
from . import ibeacon

logger = logging.getLogger(__name__)

class PresenceSensor():
	"""
	Implement a sensor to monitor if house is occupied using iBeacon key fobs
	- Callback functions may be set for last-one-out and welcome events.
	- PresenceSensor.query(beacon_owner) method returns True if beacon registered to
	  beacon_owner is found, False otherwise
	"""
	# define required iBeacon ID keys
	BEACON_ID_KEYS = ("UUID", "Major", "Minor")
	
	def __init__(self, welcome_callback=None, last_one_out_callback=None, hci='hci0', scan_timeout=datetime.timedelta(seconds=300)):
		self.hci = hci
		self.scan_timeout = scan_timeout
		# set callback functions (if supplied as arguments)
		self.welcome_callback = welcome_callback
		self.last_one_out_callback = last_one_out_callback
		
		self.registered_beacons = []
		
		# thread lock
		self.lock = threading.Lock()
			
	def register_beacon(self, beacon, owner):
		# add beacon to list of registered beacons
		for key in PresenceSensor.BEACON_ID_KEYS:
			if key not in list(beacon.keys()): 
				return "Failed to register beacon (missing or invalid ID)"
		if self._get_beacon(beacon) == None:
			self.registered_beacons.append({"owner": owner, "ID": beacon, "last_seen": datetime.datetime.now(), "in": False})
			return "Registered beacon %s to owner %s" % (beacon, owner)

	def deregister_beacon(self, beacon):
		self.registered_beacons.remove(self._get_beacon(beacon))
		return "Deregistered beacon %s" % (beacon)

	def start(self):
		logger.info("Starting Presence Sensor...")
		self.on = True

		# start client and connect to ibeacon server
		self.client_thread = threading.Thread(target=self._client)
		self.client_thread.start()

		# start loop for presence sensor in new thread
		self.loop_thread = threading.Thread(target=self._loop)
		self.loop_thread.start()

	def stop(self):
		logger.info("Stopping Presence Sensor...")
		self.on = False
		# To-do: stop client thread
		self.loop_thread.join()
		logger.debug("Presence Sensor stopped")

	def query(self, beacon_owner=None):
		if beacon_owner is None:
			occupied = False
			for b in self.registered_beacons:
				if b['in']: occupied = True
			return occupied
		else:
			for b in self.registered_beacons:
				if b['owner'] == beacon_owner:
					return b['in']

	def _client(self):
		# start client and connect to ibeacon server
		server_address = ('localhost', 9999)
		self.client = ibeacon.Client(server_address, on_message=self._handle_message)
	
	def _loop(self):
		logger.debug("Starting loop...")
		while self.on:
			# if each beacon not seen for > SCAN_TIMEOUT then set 'in' to False. Call 
			# last_one_out_callback() first time no beacons found after timeout.
			now = datetime.datetime.now()
			beacons_found = 0
			with self.lock:
				for b in self.registered_beacons:
					if now - b['last_seen'] > self.scan_timeout:
						if b['in']: logger.info(('[%s] Bye %s!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), b['owner'])))
						b['in'] = False
					else:
						beacons_found += 1
			if (beacons_found == 0) and (beacons_found_last_loop > 0):
					self.last_one_out_callback()
			beacons_found_last_loop = beacons_found
			time.sleep(0.1)
	
	def _handle_message(self, message):
		# parse beacon IDs from message and fetch beacon from registered list
		logger.debug(message)
		beacon = self._get_beacon(message)
		# if beacon is registered
		if (beacon != None):
			# update last seen datetime and set 'in' to True
			with self.lock:
				beacon['last_seen'] = datetime.datetime.now()
				logger.debug("Beacon %s seen at %s" % (beacon['ID'], beacon['last_seen'].strftime('%Y-%m-%d %H:%M:%S')))
				if beacon['in'] == False:
					beacon['in'] = True		
			self.welcome_callback(beacon['owner'])

	def _get_beacon(self, beacon):
		for b in self.registered_beacons:
			if b['ID'] == beacon:
				return b
		return None
