#!/usr/local/bin/python3

import socket
import sys
import time
import subprocess
import threading
import logging
import struct
import json
import os

DEVNULL = open(os.devnull, 'wb')	# /dev/null
PLATFORM = os.uname()[0]

# set up logging
logger = logging.getLogger(__name__)

class Scanner():
	"""
	Listen for ibeacon advertisements and send them to each client
	"""
	def __init__(self, hci='hci0'):
		
		# bluetooth interface
		self.hci = hci
		
		# list to hold client connections
		self.clients = []

		# events used to stop child threads
		self.stop_event = threading.Event()
				
	def start(self, host='localhost', port=9999):

		# start scanning for bluetooth packets in subprocess
		self.lescan_p = subprocess.Popen(['hcitool', '-i', self.hci, 'lescan', '--duplicates'], stdout=DEVNULL)
		# start hcidump to pipe raw bluetooth packets		
		logger.debug("Running on Linux...")
		hcidump_args = ['hcidump', '--raw', '-i', self.hci]
		self.hcidump_p = subprocess.Popen(hcidump_args, stdout=subprocess.PIPE)

		self.scan_thread = threading.Thread(target=self.scan_loop)
		self.scan_thread.start()

		# create a TCP/IP socket for the server
		self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		# bind the socket to the port
		server_address = (host, port)
		print('Starting ibeacon server on %s:%s. Press Ctrl+C to exit.' % (server_address))
		self.s.settimeout(5)
		self.s.bind(server_address)
		# listen for incoming connections
		self.s.listen(1)

		self.server_thread = threading.Thread(target=self.wait_for_connections)
		self.server_thread.start()		

	def wait_for_connections(self):
		print('Waiting for connections...')
		while not self.stop_event.isSet():
			# accept incoming connections
			try:
				conn, client_address = self.s.accept()
			except socket.timeout:
				pass
			else:
				client = _ClientConnection(conn, client_address)
				self.clients.append(client)
				client.start()
		logger.debug('Server stopped')
			
	def scan_loop(self):
		"""
		Parse ibeacon advertisements from bluetooth packets
		"""
		packet = ''
		while not self.stop_event.isSet():
			line = str(self.hcidump_p.stdout.readline(), encoding='utf-8')
			line = line.replace(' ','').strip('\n')
			if line != '' and line[0] == '>':	# signifies start of next packet
				line = line[1:]	# trim leading '>'
				if packet != '':
					logger.debug(packet)
					# check this is an ibeacon packet by checking the first 5 bytes
					if packet.find('043E2A0201') == 0:
						uuid = '-'.join((packet[46:54], packet[54:58], packet[58:62], packet[62:66], packet[66:78]))
						major = int(packet[78:82], base=16)
						minor = int(packet[82:86], base=16)
						rssi = int(packet[88:90], base=16) - 256
						msg = '{"UUID":"%s","Major":"%s","Minor":"%s","RSSI":%s}' % (uuid, major, minor, rssi)
						for client in self.clients:
							client.add_to_queue(msg)
						logger.debug(msg)
				packet = ''	# empty string ready for next packet
			packet += line
		logger.debug('Scanner stopped')
				
	def stop(self):
		self.stop_event.set()
		self.scan_thread.join()
		self.server_thread.join()
		for client in self.clients:
			client.join()
		print('Bye!')
		

class Client():
	def __init__(self, server_address, on_message=None):
		self.server_address = server_address
		self.message_handler = on_message
		
		# create a TCP/IP socket
		self.s = _Socket()
		
		# connect the socket to the port where the server is listening
		logger.debug('Connecting to ibeacon server at  %s:%s' % (self.server_address))
		self.s.connect(self.server_address)
		logger.debug('Connected!')

		try:
			while True:
				data = self.s.recv(2)
				(packet_len,) = struct.unpack('<H',data)
				packet = self.s.recv(packet_len)
				msg = json.loads(str(packet, encoding='utf-8'))
				self.message_handler(msg)
		
		finally:
			self.s.close()
	
			
class _ClientConnection(threading.Thread):
	"""
	Send ibeacon advertisements to client
	"""
	def __init__(self, conn, client_address):
		super(_ClientConnection, self).__init__()
		self.conn = conn
		self.client_address = client_address
		print('Connection received from %s' % (client_address[0]))		
		self.queue = []
		self.stoprequest = threading.Event()
	
	def run(self):
		while not self.stoprequest.isSet():
			if len(self.queue) != 0:
				msg = self.queue.pop()
				msg_len = len(msg)
				data = struct.pack('<H', msg_len) + msg.encode('utf-8')
				logger.debug('Sending: %s' % (data))
				try:
					self.conn.sendall(data)
				except BrokenPipeError:
					logger.debug('Client at %s disconnected unexpectedly' % (self.client_address[0]))
					break
		self.conn.close()
		print('Connection to client at %s lost' % (self.client_address[0]))
	
	def add_to_queue(self, packet):
		self.queue.append(packet)
	
	def join(self, timeout=None):
		logger.debug('Stopping connection thread')
		self.stoprequest.set()
		super(_ClientConnection, self).join(timeout)


class _Socket():
	"""
	Simple socket class
	"""
	def __init__(self, sock=None):
		if sock is None:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		else:
			self.sock = sock
	
	def connect(self, server_address):
		self.sock.connect(server_address)
		
	def send(self, msg):
		totalsent = 0
		while totalsent < len(msg):
			sent = self.sock.send(msg[totalsent:])
			print('Sent: %s' % (sent))
			if sent == 0:
				raise RuntimeError('socket connection broken')
			totalsent = totalsent + sent
		
	def recv(self, msg_len):
		chunks = []
		bytes_recd = 0
		while bytes_recd < msg_len:
			chunk = self.sock.recv(min(msg_len - bytes_recd, 2048))
			if chunk == b'':
				raise RuntimeError('socket connection broken')
			chunks.append(chunk)
			bytes_recd = bytes_recd + len(chunk)
		return b''.join(chunks)
		
	def close(self):
		self.sock.close()
