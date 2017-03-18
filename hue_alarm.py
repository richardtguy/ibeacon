import soco
import requests
import time
import threading
import logging

"""
# get uri for tracks currently playing on each speaker
print('Connecting to Sonos speakers...')
sonos = soco.discover()
for speaker in sonos:
	current_track = speaker.get_current_track_info()
	print('{}: {}'.format(speaker.player_name, current_track['uri']))
"""

logger = logging.getLogger(__name__)

class HueAlarm():
	
	def __init__(self, ip, username, sensors, red_alert=None, ifttt_key=None):
		logger.info("Initialising Alarm...")
		self.HUE_IP_ADDRESS = ip
		self.HUE_USERNAME = username
		self.RED_ALERT = red_alert
		self.sensors = sensors
		self.ifttt_key = ifttt_key
		self.armed = False

	def alert(self, id):
		"""
		Alert
		"""
		url = 'http://'+self.HUE_IP_ADDRESS+'/api/'+self.HUE_USERNAME+'/lights/'+id+'/state'
		payload = {"alert": "lselect",  "sat":254, "hue":0}
		r = requests.put(url, json=payload)

	def arm(self):
		# poll motion sensors and trigger alert if motion detected (blocking)
		self.armed = True
		self.alarm_thread = threading.Thread(target=self._loop)
		logger.debug("Alarm system armed...")
		self.alarm_thread.start()

	def _loop(self):
		url = 'http://'+self.HUE_IP_ADDRESS+'/api/'+self.HUE_USERNAME+'/sensors/'
		while self.armed:
			for sensor_id in self.sensors:
				sensor = requests.get(url+sensor_id).json()
				if sensor['state']['presence'] == True:
					self.trigger_alarm()
			time.sleep(2)

	def disarm(self):
		self.armed = False
		self.alarm_thread.join()
		logger.debug("Alarm system disarmed")

	def trigger_alarm(self):
		logger.info("Alarm triggered!")
		print("Alarm triggered!")
		"""
		# initialise lights	and start flashing
		url = 'http://'+self.HUE_IP_ADDRESS+'/api/'+self.HUE_USERNAME+'/lights'
		r = requests.get(url).json()
		for light_id in r:
			self.alert(light_id)

		# play track with specified uri
		speakers = soco.discover()
		for speaker in speakers:
			speaker.volume = 25
			speaker.play_uri(uri=self.RED_ALERT)
		"""
			
		# send notification to Richard's phone
		r = requests.get('https://maker.ifttt.com/trigger/alarm_triggered/with/key/'+self.ifttt_key)


if __name__ == '__main__':

	# Hue bridge configuration
	HUE_IP_ADDRESS = '192.168.1.1'
	HUE_USERNAME = 'Xyy5xjGvRcbd7HUimB2g1Ci21AliT5IHmIK2uR-O'

	# Track UID
	RED_ALERT = 'x-sonos-http:_dklxfo-EJNeI034TlujxxT3CcvEL_TI-ykZUNyBhM2Y3sn-ZNvklU7USMLup_sP.mp3?sid=151&flags=8192&sn=1'

	# Motion sensor IDs
	sensors = ['3','7']
	
	# IFTTT key
	ifttt_key = 'bZ9sX0SHeE5PeLAJQh3D4B'

	alarm = HueAlarm(HUE_IP_ADDRESS, HUE_USERNAME, RED_ALERT, sensors, ifttt_key)
	alarm.arm()
