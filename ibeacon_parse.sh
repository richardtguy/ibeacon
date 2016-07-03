#!/bin/bash
# parse raw Bluetooth packets from `hcidump --raw` and output ibeacon advertisements in JSON format

function parse_ib_uuid {
    UUID=`echo $1 | sed 's/^.\{69\}\(.\{47\}\).*$/\1/'`
    UUID=`echo $UUID | sed -e 's/\ //g' -e 's/^\(.\{8\}\)\(.\{4\}\)\(.\{4\}\)\(.\{4\}\)\(.\{12\}\)$/\1-\2-\3-\4-\5/'`
}

function parse_ib_major {
    MAJOR=`echo $1 | sed 's/^.\{117\}\(.\{5\}\).*$/\1/'`
    MAJOR=`echo $MAJOR | sed 's/\ //g'`
    MAJOR=`echo "ibase=16; $MAJOR" | bc`
}

function parse_ib_minor {
    MINOR=`echo $1 | sed 's/^.\{123\}\(.\{5\}\).*$/\1/'`
    MINOR=`echo $MINOR | sed 's/\ //g'`
    MINOR=`echo "ibase=16; $MINOR" | bc`
}

function parse_ib_power {
    POWER=`echo $1 | sed 's/^.\{129\}\(.\{2\}\).*$/\1/'`
    POWER=`echo "ibase=16; $POWER" | bc`
    POWER=$[POWER - 256]
}

function parse_rssi {
      LEN=$[${#1} - 2]
      RSSI=`echo $1 | sed "s/^.\{$LEN\}\(.\{2\}\).*$/\1/"`
      RSSI=`echo "ibase=16; $RSSI" | bc`
      RSSI=$[RSSI - 256]
}

function parse_wp_battery {
    BATTERY=`echo $1 | sed 's/^.\{63\}\(.\{2\}\).*$/\1/'`
    BATTERY=`echo "ibase=16; $BATTERY" | bc`
}


packet=""
capturing=""
count=0
while read line
do
	count=$[count + 1]
	if [ "$capturing" ]; then
		if [[ $line =~ ^[0-9a-fA-F]{2}\ [0-9a-fA-F] ]]; then
			packet="$packet $line"
		else
			if [[ $packet =~ ^04\ 3E\ 2A\ 02\ 01\ .{26}\ 02\ 01 ]]; then
				parse_ib_uuid "$packet"
				parse_ib_major "$packet"
				parse_ib_minor "$packet"
				parse_ib_power "$packet"
				parse_rssi "$packet"
				if [[ $packet =~ ^04\ 3E\ 2A\ 02\ 01\ .{26}\ 02\ 01\ .{17}\ (30|31) ]]; then
					parse_wp_battery "$packet"
				fi
				echo "{\"UUID\": \"$UUID\", \"Major\": \"$MAJOR\", \"Minor\": \"$MINOR\", \"Power\": $POWER, \"RSSI\": $RSSI}"
			fi
			capturing=""
			packet=""
		fi
	fi

	if [ ! "$capturing" ]; then
		if [[ $line =~ ^\> ]]; then
			packet=`echo $line | sed 's/^>.\(.*$\)/\1/'`
			capturing=1
		fi
	fi
done
