#!/usr/local/bin/python3

__version__ = 5

import socket, binascii, struct, time, logging
import uid as uid_module

COMMAND_ALL_LIGHT_STATUS = 0x13
COMMAND_BRI = 0x31
COMMAND_ONOFF = 0x32
COMMAND_TEMP = 0x33
COMMAND_LIGHT_STATUS = 0x68

ON = True
OFF = False

PORT = 4000

logger = logging.getLogger(__name__)

class Lightify():
	"""
	Base class with methods for communicating with Lightify Gateway
	"""
	def __init__(self, host, port=PORT):
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
	
class LightifyLight(Lightify):
	"""
	Implement an API for an Osram Lightify light (on/off, save & recall state).
	This object communicates with lights via a Lightify Gateway, using a binary protocol.
	"""			
	def __init__(self, addr, host, name=None, port=PORT, uid=None):
		super(LightifyLight, self).__init__(host, port)		
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
		logger.info('Switching light %s on' % (self._name))
		self._recall_state(self._state, transition=transition)
		
	def off(self, transition=10):
		"""
		Switch the light off
		"""
		if transition == False: transition = 10
		logger.info('Switching light %s off' % (self._name))		
		self.set_bri(0, transition=transition)

	def save_state(self):		
		"""
		Return current state of light (query Gateway)
		"""
		logger.info('Getting current state of light %s' % (self._name))		
		command = self._build_command(COMMAND_LIGHT_STATUS)
		while True:
			recvd_data = self._send_command(command)
			try:
				(on, bri, temp, r, g, b, h) = struct.unpack("<19x2BH4B3x", recvd_data)
			except(struct.error):
				logger.debug('Could not get state, trying again...')
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
		logger.debug('Setting brightness of light %s to %s' % (self._name, bri))		
		data = struct.pack("<BH",bri, transition)
		command = self._build_command(COMMAND_BRI, data=data)
		response = self._send_command(command)
		self._check_rc(response)

	def set_temp(self, temp, transition=10):
		"""
		Set the colour temperature of the light
		"""
		logger.debug('Setting temp of light %s to %s' % (self._name, temp))		
		data = struct.pack("<HH", temp, transition)
		command = self._build_command(COMMAND_TEMP, data=data)
		response = self._send_command(command)
		self._check_rc(response)

	def _on_off(self, on_off):
		"""
		Switch the light on or off
		"""
		logger.debug('Switching light on to %s' % (self._name, on_off))	
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

class LightifyGateway(Lightify):

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
			light = LightifyLight(addr, self._host, name=name)
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
