#!/usr/bin/env python3
#
# (C) 2019 by Jose M. Guisado <jmgg@riseup.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from collections import namedtuple
from datetime import datetime

import argparse
import csv
import gzip
import ipaddress
import os
import requests
import shutil
import sys
import time
import unicodedata


# entries in DB-IP geoip csv
NetworkEntry = namedtuple('NetworkEntry',
                          'network_first, '
                          'network_last, '
                          'country_alpha_2')


def strip_accent(text):
    """
    Remove accented characters. Convert to ASCII.
    """
    return ''.join(char for char in unicodedata.normalize('NFKD', text)
                   if unicodedata.category(char) != 'Mn')


def format_dict(dictionary):
    """
    Strip accents and replace special characters for keys and values
    inside a dictionary
    """
    new_dict = {}
    for key, value in dictionary.items():
        if key != '' and value != '':
            new_key = strip_accent(key).lower()
            new_key = new_key.replace(' ', '_').replace('[', '').replace(']', '').replace(',', '')
            new_value = strip_accent(value).lower()
            new_value = new_value.replace(' ', '_').replace('[', '').replace(']', '').replace(',','')
            new_dict[new_key] = new_value
        else:
            sys.exit('BUG: There is an empty string as key or value inside a dictionary')

    return new_dict


def check_ipv4(addr):
    """
    Returns true if a string is representing an ipv4 address.
    False otherwise.
    """
    try:
        ipaddress.IPv4Address(addr)
        return True
    except ipaddress.AddressValueError:
        return False


def make_chinaip_dict():
    """
    Read DB-IP network ranges and creates china ip4 dictionaries
    """
    chinaip_dict = {}

    for net_entry in map(NetworkEntry._make, csv.reader(args.blocks)):

        alpha2 = net_entry.country_alpha_2
        # codes not equal 'CN' will be ignored
        if alpha2 != 'CN':
            continue

        # There are entries in DB-IP csv for single addresses which
        # are represented as same start and end address range.
        # nftables does not accept same start/end address in ranges
        if net_entry.network_first == net_entry.network_last:
            k = net_entry.network_first
        else:
            k = '-'.join((net_entry.network_first, net_entry.network_last))

        if check_ipv4(net_entry.network_first):
                chinaip_dict[k] = alpha2

    return format_dict(chinaip_dict)


def make_lines(dictionary):
    """
    For each entry in the dictionary maps to a line for nftables dict files
    using key literal and value as nft variable.
    """
    return ['{} : 156'.format(k) for k, v in dictionary.items()]


def write_nft_header(f):
    """
    Writes nft comments about generation date and db-ip copyright notice.
    """
    f.write("# Generated by nft_geoip.py on {}\n"
            .format(datetime.now().strftime("%a %b %d %H:%M %Y")))
    f.write("# IP Geolocation by DB-IP (https://db-ip.com) licensed under CC-BY-SA 4.0\n\n")

def write_chinaips(chinaip_dict):
    """
    Write ipv4 chinaip nftables maps to corresponding output files.
    """
    with open(args.dir+'chinaip-ipv4.nft', 'w') as output_file:
        write_nft_header(output_file)
        output_file.write('map chinaip4 {\n'
                          '\ttype ipv4_addr : mark\n'
                          '\tflags interval\n'
                          '\telements = {\n\t\t')

        output_file.write(',\n\t\t'.join(make_lines({k:v.upper() for k,v in chinaip_dict.items()})))
        output_file.write('\n')
        output_file.write('\t}\n')
        output_file.write('}\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Creates nftables chinaip definitions and maps.')
    parser.add_argument('--file-address',
                        type=argparse.FileType('r'),
                        help='path to db-ip.com lite cvs file with ipv4 and ipv6 geoip information',
                        required=False,
                        dest='blocks')
    parser.add_argument('-d', '--download', action='store_true',
                        help='fetch geoip data from db-ip.com. This option overrides --file-address',
                        required=False,
                        dest='download')
    parser.add_argument('-o', '--output-dir',
                        help='Existing directory where downloads and output will be saved. \
                              If not specified, working directory',
                        required=False,
                        dest='dir')
    args = parser.parse_args()

    if not args.dir:
        args.dir = ''
    elif not os.path.isdir(args.dir):
        parser.print_help()
        sys.exit('\nSpecified output directory does not exist or is not a directory')
    else:
        # Add trailing / for folder path if there isn't
        args.dir += '/' if args.dir[-1:] != '/' else ''

    if args.download:
        filename = args.dir+'dbip.csv.gz'
        url = 'https://download.db-ip.com/free/dbip-country-lite-{}.csv.gz'.format(time.strftime("%Y-%m"))
        print('Downloading db-ip.com geoip csv file...')
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(filename, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
        else:
            sys.exit('Error trying to download DB-IP lite geoip csv file. Bailing out...')

        with gzip.open(filename, 'rb') as f_in:
            with open(args.dir+'dbip.csv', 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
                os.remove(filename)

        # Update blocks arg with the downloaded file
        args.blocks = open(args.dir+'dbip.csv', 'r', encoding='utf-8')

    if not args.blocks:
        parser.print_help()
        sys.exit('Missing geoip address csv file. You can instead download it using --download.')

    print('Writing nftables maps chinaip-ipv4.nft...')
    chinaip_dict = make_chinaip_dict()
    write_chinaips(chinaip_dict)
    print('Done!')
