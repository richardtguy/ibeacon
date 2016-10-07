import random

# helper function to generate random unique IDs 
def get_UID(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', length=8):
	ID = ''
	for c in range(length):
		rand_index = random.randrange(len(alphabet))
		char = alphabet[rand_index]
		ID = ID + char
	return ID