#!/usr/local/bin/python3

from jubilee import lights

base_address = '192.168.1.'

success = False

for i in range(32):
	ip = base_address + str(i)
	lightify = lights.LightifyGateway(ip)
	try:
		lightify.get_all_lights()
	except:
		pass
	else:
		print("Found Lightify Gateway at: {}".format(ip))
		success = True
		break

if not success:
	print('Lightify Gateway not found!')