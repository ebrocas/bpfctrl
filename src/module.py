#!/usr/bin/env python3
# Copyright (C) 2019 Stamus Networks
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

"""A bpftool wrapper to handle eBPF maps"""

import ipaddress
import json
import socket
import subprocess
import sys
import shutil


class BpfException(BaseException):
    """
    Generic class for bpfctrl exception
    """
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __unicode__(self):
        return self.value


class Ipv4:
    """
        Handle IPV4 addresses
    """

    def __init__(self, ip_add):
        try:
            self.ipaddress = ipaddress.ip_address(int(ip_add))
        except ValueError:
            self.ipaddress = ipaddress.ip_address(ip_add)

    def htonl(self):
        """transform self.ipaddress by applying htonl to it"""
        ip_int = int(self.ipaddress)
        self.ipaddress = ipaddress.ip_address(socket.htonl(ip_int))
        return self

    def ntohl(self):
        """transform self.ipaddress by applying ntohl to it"""
        ip_int = int(self.ipaddress)
        self.ipaddresss = ipaddress.ip_address(socket.ntohl(ip_int))
        return self

    def to_str(self):
        """:return: the ipaddress as a string"""
        return str(self.ipaddress)

    def to_byte_array(self):
        """
            :return: an array obtained by the transformation of the ipaddress into
            an array of byte values
        """
        ip_str = self.to_str()
        return ip_str.split(".")


class U32:
    def __init__(self, value):
        self.value = int(value)

    def to_byte_array(self):
        """Return the corresponding byte array of length 4"""
        val = str(ipaddress.ip_address(self.value))
        return val.split(".")


class HexArray:
    """
        Handle of hexadecimal arrays that corresponds to the value of each bytes
        ["0xaa", "0xbb", etc.] and enable to transforming it into several types.
    """

    def __init__(self, hex_array):
        self.hex = ''.join(['{0[2]}{0[3]}'.format(el) for el in hex_array])

    def to_ip(self):
        """:return: the IP address corresponding to the hexadecimal array"""
        ip_obj = Ipv4(bytes.fromhex(self.hex))
        ip_obj.ntohl()
        return ip_obj

    def to_int(self):
        """:return: the integral number corresponding to the hexadecimal array"""
        return int(self.hex, 16)


class Map:
    def __init__(self, path_to_map, map_type, json_bool=False, cpu_bool=False):
        self.path = path_to_map
        self.type = map_type
        self.json = json_bool
        self.cpu = cpu_bool
        if shutil.which("bpftool") is None:
            raise BpfException("Bpftool not found")

    def __str__(self):
        return self.path

    def __unicode__(self):
        return self.path

    def u32_obj_convertion(self, val_str):
        """Return an U32 object or exit with an eror if it is not an int"""
        try:
            val_u32 = U32(val_str)
        except ValueError:
            raise BpfException(
                "ValueError: {} does not appear to be an int".format(val_str))
        else:
            return val_u32

    def exit_bpf_error(self, errno, error):
        """
            Exit with the error returned by bpf.
    
            :param stdout: output of the bpftool command like :
                           '{"error":"bpf obj get (/sys/fs/bpf): Permission
                            denied"}\n'
        """
        error = error.replace('"', "").replace("\n", "")
        if error == "null":
            raise BpfException("invalid parameter or not found")
    
        error_split = error[1:].split(":")
        exit_message = error_split[2].replace("}", "")
        raise BpfException(exit_message.lstrip())

    def _command_action(self, action, key):
        """Create a list of commands to do action on the map with the key"""
        command = ["bpftool", "map", action, "pinned", self.path, "key"]
        command.extend(key)
        return command

    def _modification(self, action, keys, values=None):
        """
            Add or remove key of the eBPF map given.
            A key and a value are two arrays of the same length. Each element
            of an array correspond to the value taken by the byte. It is an
            str(int).

            :param action: "update" or "delete"
            :param keys: a list of keys
            :param values: a list of the values associated with the ip of ips
            :return: None
        """
        len_keys = len(keys)
        for i in range(len_keys):
            command = self._command_action(action, keys[i])
            if action == "update":
                command.append("value")
                command.extend(values[i])
            call = subprocess.run(command, encoding='utf-8',
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if call.returncode != 0:
                self.exit_bpf_error(call.returncode, call.stderr)

    def __cpu_parse(self, json_result, dict_bool):
        """
            Parse a list of dictionnaries [{'cpu', 'value'} into a dictionnary
            or the sum of all the 'value'.

            :param json_result: a list of dictionnaries {'cpu', 'value'} where
                                'cpu' value is an int and 'value' value is an
                                array of hexadecimal number ["0xaa", ...]
            :param dict_bool: if True the result is a dictionnary, else an int.
            :return: a dictionnary {cpu:value, ...} or the sum of all the values.
        """
        vals = []
        for j in json_result:
            hex_value = HexArray(j['value'])
            vals.append((j['cpu'], hex_value.to_int()))
        vals = dict(vals)
        if dict_bool:
            return vals
        return sum(vals.values())

    def __key_transformation_to_ip(self, ip_hexarray):
        ip_addr = ip_hexarray.to_ip()
        return ip_addr.to_str()

    def _parse_json_output(self, json_output):
        """
            Parse a json output of a bpftool command, transform it in a
            dictionnary {ip:{cpu:int}} or {ip:int}. The value is computed by
            transforming the hexademimal values of the json output into an int.

            :param json_output: a dictionnary (obtained with json.load)
            :return: a dictionnary
        """
        key_transformation = {
            'ipv4': self.__key_transformation_to_ip,
            'uniq': (lambda key: key.to_int())}

        output = []
        if not isinstance(json_output, list):
            json_output = [json_output]
        for j in json_output:
            key_hex = HexArray(j['key'])
            key = key_transformation[self.type](key_hex)
            try:
                dump_value = j['values']
            except KeyError:
                dump_value = HexArray(j['value'])
                value = dump_value.to_int()
            else:
                value = self.__cpu_parse(dump_value, self.cpu)
            output.append((key, value))
        return dict(output)

    def _output_string(self, dic):
        """
            Given a dict dic={key:value} or {key:{cpu : val}}, create the
            output of the programm and return it as a string. It can be in JSON
            format if json_flag is True.
            If it is not in JSON format, the output is :
            KEY   VALUE or KEY   VAL0   VAL1   VAL2   ...
        """
        if self.json:
            return json.dumps(dic, indent=4)

        res = ""
        if not dic:
            return res
        keys = list(dic.keys())
        if isinstance(dic[keys[0]], int):
            for k in keys:
                res += "{}    {}\n".format(k, dic[k])
        else:
            for k in keys:
                values = list(dic[k].values())
                res += k + "    "
                res += "    ".join(['{}'.format(val) for val in values]) + "\n"
        return res[0:len(res) - 1]

    def dump(self, path_to_dump_file):
        """
            Print the dump of the eBPF map given or store it into a JSON file.

            :param path_to_dump_file: path to the file in which the dump will
                                      be stored,
                                       None if the dump is displayed on stdout.
            :return: None
        """
        call = subprocess.run(["bpftool", "map", "dump", "pinned", self.path, "-j"],
                              encoding='utf-8', stdout=subprocess.PIPE)

        if call.returncode != 0:
            self.exit_bpf_error(call.returncode, call.stderr)

        dump = json.loads(call.stdout)
        dic = self._parse_json_output(dump)
        if self.type == 'uniq':
            output = dic[0]
        else:
            output = self._output_string(dic)
        if path_to_dump_file is None:
            return output
        else:
            with open(path_to_dump_file, 'w') as file:
                file.write(output)
            file.close()


class MapIpv4(Map):
    """
        Maps in which keys are IPv4 addresses.
    """

    def __init__(self, path_to_map, json_bool=False, cpu_bool=False):
        Map.__init__(self, path_to_map, 'ipv4', json_bool, cpu_bool)

    def ipv4_obj_convertion(self, ip_str):
        """Return an Ipv4 object or exit with an eror if it is not a ipaddress"""
        try:
            ip_addr = Ipv4(ip_str).htonl()
        except ValueError:
            raise BpfException(
                "ValueError: {} does not appear to be an IPv4 address".format(ip_str))
        else:
            return ip_addr

    def __add_conversion(self, ipval):
        """ Conter a list of "ip=value" into a list of [Ipv4, U32]"""
        res = []
        for couple in ipval:
            ip_val = couple.split("=")
            if len(ip_val) == 1:
                ip_val.append('')
            ip_val[0] = self.ipv4_obj_convertion(ip_val[0])
            ip_val[1] = self.u32_obj_convertion(ip_val[1])
            res.append(ip_val)
        return res

    def add(self, ip_val):
        """
            Add all the ips given in the map with their associated value.

            :param ip_val: a list of "ip=value"
            :return: None
        """
        array_ip_val = self.__add_conversion(ip_val)
        add_ips = list(map(lambda pos: pos[0].to_byte_array(), array_ip_val))
        add_vals = list(
            map(lambda pos: pos[1].to_byte_array(), array_ip_val))
        self._modification("update", add_ips, add_vals)

    def remove(self, ips_str):
        """
            Remove all the ips given of the maps.

            :param ips_str: a list of IPv4 adresses (str).
            :return: None
        """
        ips_bytes = list(
            map(lambda pos: self.ipv4_obj_convertion(pos).to_byte_array(), ips_str))
        self._modification("delete", ips_bytes)

    def get(self, ip_key):
        """
            Chek if an IP address is in the eBPF map given, if it is, display
            its value, else exit with an error.

            :param ip_key: the ip to check (Ipv4 object)
            :return: None
        """
        ip_obj = self.ipv4_obj_convertion(ip_key)
        command = self._command_action("lookup", ip_obj.to_byte_array())
        command.append("-p")
        call = subprocess.run(command, encoding='utf-8',
                              stdout=subprocess.PIPE)

        res = call.stdout
        if call.returncode != 0:
            if call.returncode == 255 and res == "null\n":
                raise BpfException("The key {} is not in the map {}.".format(
                    ip_key, self))
            else:
                self.exit_bpf_error(call.returncode, call.stdout)

        output = self._parse_json_output(json.loads(res))
        return(self._output_string(output))


class MapUniq(Map):
    """
        Maps in which there is only an int (u32) and key is all 0.
    """

    def __init__(self, path_to_map, json_bool=False):
        Map.__init__(self, path_to_map, 'uniq', json_bool, False)

    def set(self, val):
        """Set the value of the map at val. val is a U32 object"""
        key = U32(0).to_byte_array()
        val_u32 = self.u32_obj_convertion(val)
        self._modification("update", [key], [val_u32.to_byte_array()])
