# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

try:
    from urllib.request import urlopen
    from urllib.error import HTTPError
except:
    from urllib2 import urlopen, HTTPError

import pexpect
import dlipower
import time


try:
    from ouimeaux.environment import Environment as WemoEnv
    from ouimeaux.device.switch import Switch as WemoSwitch
except:
    WemoEnv = None
    WemoSwitch = None

def get_power_device(ip_address, username=None, password=None, outlet=None):
    '''
    Try to determine the type of network-controlled power switch
    at a given IP address. Return a class that can correctly
    interact with that type of switch.
    '''

    if ip_address is None:
        if outlet is not None:
            if "wemo://" in outlet:
                if WemoEnv is None:
                    print("Please install ouimeaux: pip install ouimeaux")
                else:
                    return WemoPowerSwitch(outlet=outlet)
            if "serial://" in outlet:
                return SimpleSerialPower(outlet=outlet)
            if "cmd://" in outlet:
                return SimpleCommandPower(outlet=outlet)

        return HumanButtonPusher()

    try:
        data = urlopen("http://" + ip_address).read().decode()
    except HTTPError as e:
        data = e.read().decode()
    except Exception as e:
        print(e)
        raise Exception("\nError connecting to %s" % ip_address)
        
    print("data = %s" % data)
    if '<title>Power Controller' in data:
        return DLIPowerSwitch(ip_address, outlet=outlet, username=username, password=password)
    if 'Sentry Switched CDU' in data:
        return SentrySwitchedCDU(ip_address, outlet=outlet)
    if '<title>APC ' in data:
        return APCPower(ip_address, outlet=outlet)
    if '<b>IP9258 Log In</b>' in data:
        return Ip9258(ip_address, outlet, username=username, password=password)
    if 'Access Error: Unauthorized' in data:
        print("ip_address = %s" % ip_address)
        print("outlet = %s" % outlet)
        return Ip9820(ip_address, outlet)
    else:
        raise Exception("No code written to handle power device found at %s" % ip_address)


class PowerDevice():
    '''
    At minimum, power devices let users reset an outlet over a network.
    '''

    def __init__(self, ip_address, username=None, password=None):
        self.ip_address = ip_address
        self.username = username
        self.password = password
        # Maybe verify connection is working here

    def reset(self, outlet):
        '''Turn an outlet OFF, maybe wait, then back ON.'''
        raise Exception('Code not written to reset with this type of power device at %s' % self.ip_address)


class SentrySwitchedCDU(PowerDevice):
    '''
    Power Unit from Server Technology.
    '''
    def __init__(self,
                 ip_address,
                 outlet,
                 username='admn',
                 password='admn'):
        PowerDevice.__init__(self, ip_address, username, password)
        self.outlet = outlet
        # Verify connection
        try:
            pcon = self.__connect()
            pcon.sendline('status .a%s' % self.outlet)
            i = pcon.expect(['Command successful', 'User/outlet -- name not found'])
            if i == 1:
                raise Exception('\nOutlet %s not found' % self.outlet)
            pcon.close()
        except Exception as e:
            print(e)
            print("\nError with power device %s" % ip_address)
            raise Exception("Error with power device %s" % ip_address)

    def __connect(self):
        pcon = pexpect.spawn('telnet %s' % self.ip_address)
        pcon.expect('Sentry Switched CDU Version', timeout=15)
        pcon.expect('Username:')
        pcon.sendline(self.username)
        pcon.expect('Password:')
        pcon.sendline(self.password)
        i = pcon.expect(['Switched CDU:', 'Critical Alert'])
        if i == 0:
            return pcon
        else:
            print("\nCritical failure in %s, skipping PDU\n" % self.power_ip)
            raise Exception("critical failure in %s" % self.power_ip)

    def reset(self, retry_attempts=2):
        print("\n\nResetting board %s %s" % (self.ip_address, self.outlet))
        for attempt in range(retry_attempts):
            try:
                pcon = self.__connect()
                pcon.sendline('reboot .a%s' % self.outlet)
                pcon.expect('Command successful')
                pcon.close()
                return
            except Exception as e:
                print(e)
                continue
        raise Exception("\nProblem resetting outlet %s." % self.outlet)

class HumanButtonPusher(PowerDevice):
    '''
    Tell a person to physically reboot the router.
    '''
    def __init__(self):
        PowerDevice.__init__(self, None)
    def reset(self):
        print("\n\nUser power-cycle the device now!\n")

class APCPower(PowerDevice):
    '''Resets an APC style power control port'''
    def __init__(self,
                 ip_address,
                 outlet,
                 username='apc',
                 password='apc'):
        PowerDevice.__init__(self, ip_address, username, password)
        self.outlet = outlet
    def reset(self):
        pcon = pexpect.spawn('telnet %s' % self.ip_address)
        pcon.expect("User Name :")
        pcon.send(self.username + "\r\n")
        pcon.expect("Password  :")
        pcon.send(self.password + "\r\n")
        pcon.expect("> ")
        pcon.send("1" + "\r\n")
        pcon.expect("> ")
        pcon.send("2" + "\r\n")
        pcon.expect("> ")
        pcon.send("1" + "\r\n")
        pcon.expect("> ")
        pcon.send(self.outlet + "\r\n")
        pcon.expect("> ")
        pcon.send("1" + "\r\n")
        pcon.expect("> ")
        pcon.send("6" + "\r\n")
        pcon.send("YES")
        pcon.send("" + "\r\n")
        pcon.expect("> ")

class DLIPowerSwitch(PowerDevice):
    '''Resets a DLI based power switch'''
    def __init__(self,
                 ip_address,
                 outlet,
                 username,
                 password):
        PowerDevice.__init__(self, ip_address, username, password)
        self.switch = dlipower.PowerSwitch(hostname=ip_address, userid=username, password=password)
        self.outlet = outlet

    def reset(self, outlet=None):
        if outlet is None:
            outlet = self.outlet
        self.switch.cycle(outlet)

class WemoPowerSwitch(PowerDevice):
    '''
    Controls a wemo switch given an ipaddress. Run the following command to list devices:

        $ python ./devices/power.py
    '''
    def __init__(self, outlet):
        addr = 'http://' + outlet.replace("wemo://", "") + ":49153/setup.xml"
        self.switch = WemoSwitch(addr)
    def reset(self):
        self.switch.off()
        time.sleep(5)
        self.switch.on()

class SimpleCommandPower(PowerDevice):
    '''
    Runs a simple command to turn power on/off
    '''

    on_cmd = "true"
    off_cmd = "false"

    def __init__(self, outlet):
        parsed = outlet.replace("cmd://", '').split(';')
        for param in parsed:
            for attr in ['on_cmd', 'off_cmd']:
                if attr + '=' in param:
                    setattr(self, attr, param.replace(attr + '=', '').encode())

    def reset(self):
        pexpect.spawn(self.off_cmd).expect(pexpect.EOF)
        time.sleep(5)
        pexpect.spawn(self.on_cmd).expect(pexpect.EOF)

class SimpleSerialPower(PowerDevice):
    '''
    Simple serial based relay or power on off. Has an on and off string to send
    over serial
    '''
    serial_dev = '/dev/ttyACM0'
    baud = 2400
    off_cmd = b'relay on 0'
    delay = 5
    on_cmd = b'relay off 0'

    def __init__(self, outlet):
        parsed = outlet.replace("serial://", '').split(';')
        self.serial_dev = "/dev/" + parsed[0]
        for param in parsed[1:]:
            for attr in ['on_cmd', 'off_cmd']:
                if attr + '=' in param:
                    setattr(self, attr, param.replace(attr + '=', '').encode())

    def reset(self):
        import serial
        with serial.Serial(self.serial_dev, self.baud) as ser:
            if self.off_cmd is not None:
                ser.write(self.off_cmd + '\r')
                time.sleep(5)

            ser.write(self.on_cmd + '\r')

            ser.close()

#
# IP Power 9258 networked power switch class
#
# This work is released under the Creative Commons Zero (CC0) license.
# See http://creativecommons.org/publicdomain/zero/1.0/

# Example use:
#
# import time
# from ip9258 import Ip9258
#
# ip9258 = Ip9258('192.168.1.10', 'admin', 'password')
#
# for i in range(4):
#     ip9258.on(i)
#     time.delay(1)
#
#     ip9258.off(i)
#     time.delay(1)

import urllib2
from pysnmp.carrier.asyncore.dispatch import AsyncoreDispatcher
from pysnmp.carrier.asyncore.dgram import udp
from pyasn1.codec.ber import encoder, decoder
from pysnmp.proto.api import v2c
from pysnmp.entity.rfc3413.oneliner import cmdgen
from pysnmp.proto import rfc1902

class Ip9258(PowerDevice):
    def __init__(self, ip_address, port, username="admin", password="12345678"):
        PowerDevice.__init__(self, ip_address, username, password)
        self._ip_address = ip_address
        self.port = port

        # create a password manager
        password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, 'http://' + ip_address, username, password)
        handler = urllib2.HTTPBasicAuthHandler(password_mgr)
        opener = urllib2.build_opener(handler)
        # Now all calls to urllib2.urlopen use our opener.
        urllib2.install_opener(opener)

    def on(self):
        print("Power On Port(%s)\n" % self.port)
        return urllib2.urlopen('http://' + self._ip_address + '/set.cmd?cmd=setpower+p6' + str(self.port) + '=1')

    def off(self):
        print("Power Off Port(%s)\n" % self.port)
        return urllib2.urlopen('http://' + self._ip_address + '/set.cmd?cmd=setpower+p6' + str(self.port) + '=0')

    def reset(self):
	self.off()
	time.sleep(5)
	self.on()

class Ip9820(PowerDevice):
    def __init__(self, ip_address, port):
        self.ip_address = ip_address
        self.port = port
        self.oid_Outlet = '1.3.6.1.4.1.38107.1.3'
        
    def on(self):
       oid = self.oid_Outlet + '.' + str(self.port) + '.0'
       print("set Ip9820 port on")
       Snmp("set",self.ip_address,"private",oid ,'i',1)
       result = Snmp("get",self.ip_address,"private",oid)
       print("result = %s" % result)
       return result
    
    def off(self):
        oid = self.oid_Outlet + '.' + str(self.port) + '.0'
        print("set Ip9820 port off")
        Snmp("set",self.ip_address,"private",oid ,'i',0)
        result = Snmp("get",self.ip_address,"private",oid)
        print("result = %s" % result)
        return result
    
    def reset(self):
	self.off()
	time.sleep(5)
	self.on()
    
    def getPowerStatus(self):
        oid = self.oid_Outlet + '.' + str(self.port) + '.0'
        result = Snmp("get",self.wan_ip,"private",oid)
        return result
    
    def getPowerStatusAll(self):
        oid = self.oid_Outlet
        result = Snmp("walk",self.wan_ip,"private",oid)
        return result

def Snmp(action=None, target_IP=None, community='public', oid=None, stype=None, value=None, walk_timeout=120):
    """
    Name:Snmp
    Purpose: Do snmp set,get and walk function for DUT control.
    Input:1.action
    	    2.target_IP
         3.community
         4.oid
         5.stype
         6.value
         7.walk_timeout
    Output:Snmp get or walk result
    """

    # Create command generator
    cmdGen = cmdgen.CommandGenerator()

    if action == "get":
        errorIndication, errorStatus, errorIndex, varBinds = cmdGen.getCmd(
            cmdgen.CommunityData(community),
            cmdgen.UdpTransportTarget((target_IP, 161), timeout=1, retries=3),
            oid
        )
        for name, val in varBinds:
            if val.prettyPrint() != "":
                return val.prettyPrint()
            else:
                return "null"
    elif action == "set":
        for case in switch(stype):
            if case('i'): 
                value = rfc1902.Integer(value)
                break
            elif case('s'): 
                value = rfc1902.OctetString(value)
                break 
            elif case('x'): 
                value = rfc1902.OctetString(hexValue=value)
                break 
            elif case('p'): 
                value = rfc1902.IpAddress(value)
            elif case('u'): 
                value = rfc1902.Unsigned32(value)
                break 
            elif case(): # default
                value = ""
        
        cmdGen.setCmd(
            cmdgen.CommunityData(community),
            cmdgen.UdpTransportTarget((target_IP, 161), timeout=1, retries=3),
            (oid, value)
        )

class switch(object):
    """
    Name:switch
    Purpose: def switch/case library for Snmp set used.
    Input:object ex.stype
    Output:True or False
    """
    
    def __init__(self, value):
        self.value = value
        self.fall = False
 
    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
     
    def match(self, *args):
        """Indicate whether or not to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args: 
            self.fall = True
            return True
        else:
            return False
            

if __name__ == "__main__":
    print("Gathering info about power outlets...")

    if WemoEnv is not None:
        env = WemoEnv()
        env.start()
        scan_time = 10
        print("Scanning for WeMo switches for %s seconds..." % scan_time)
        env.discover(scan_time)
        if len(env.list_switches()) > 0:
            print("Found the following switches:");
            for switch_name in env.list_switches():
                switch = env.get_switch(switch_name)
                print("%s ip address is %s" % (switch_name, switch.host))
            print("The switches above can be added by ip address"
                    " for example use the")
            print("following to use %s" % switch_name)
            print("\twemo://%s" % switch.host)
        else:
            print("No WeMo switches found")
