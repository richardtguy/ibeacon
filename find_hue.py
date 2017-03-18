#!/usr/local/bin/python3

import socket

msg = \
	'M-SEARCH * HTTP/1.1\r\n' \
	'HOST:239.255.255.250:1900\r\n' \
	'ST:upnp:rootdevice\r\n' \
	'MX:2\r\n' \
	'MAN:"ssdp:discover"\r\n'

# Set up UDP socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
s.settimeout(2)
s.sendto(msg.encode(), ('239.255.255.250', 1900) )

found_bridge = False

try:
	while found_bridge == False:
		data, addr = s.recvfrom(65507)        
		if 'IpBridge' in data.decode():
			found_bridge = True
			bridge_IP, port = (addr)
			print('Found Hue Bridge at: {}'.format(bridge_IP))
        
except socket.timeout:
	print('Hue Bridge not found!')
