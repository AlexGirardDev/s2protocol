#!/usr/bin/env python

import sys
import argparse
import pprint
import re
import json
import binascii

import mpyq

import versions
import diff


class EventFilter(object):
    def process(self, event):
        """ Called for each event in the replay stream """
        return event

    def finish(self):
        """ Called when the stream has finished """
        pass


class JSONOutputFilter(EventFilter):
    """ Added as a filter will format the event into JSON """
    def __init__(self, output):
        self._output = output

    def process(self, event):
        print >> self._output, json.dumps(event, encoding='ISO-8859-1', ensure_ascii=True, indent=4)
        return event


class NDJSONOutputFilter(EventFilter):
    """ Added as a filter will format the event into NDJSON """
    def __init__(self, output):
        self._output = output

    def process(self, event):
        print >> self._output, json.dumps(event, encoding='ISO-8859-1', ensure_ascii=True)
        return event


class PrettyPrintFilter(EventFilter):
    """ Add as a filter will send objects to stdout """
    def __init__(self, output):
        self._output = output

    def process(self, event):
        pprint.pprint(event, stream=self._output)
        return event


class TypeDumpFilter(EventFilter):
    """ Add as a filter to convert events into type information """
    def process(self, event):
        def recurse_into(value):
            if type(value) is list:
                decoded = []
                for item in value:
                    decoded.append(recurse_into(item))
                return decoded
            elif type(value) is dict:
                decoded = {}
                for key, inner_value in value.iteritems():
                    decoded[key] = recurse_into(inner_value)
                return decoded
            return (type(value).__name__, value)
        return recurse_into(event)
    

class StatCollectionFilter(EventFilter):
    """ Add as a filter to collect stats on events """
    def __init__(self):
        self._event_stats = {}

    def process(self, event):
        # update stats
        if '_event' in event and '_bits' in event:
            stat = self._event_stats.get(event['_event'], [0, 0])
            stat[0] += 1  # count of events
            stat[1] += event['_bits']  # count of bits
            self._event_stats[event['_event']] = stat
        return event

    def finish(self):
        print >> sys.stdout, 'Name, Count, Bits'
        for name, stat in sorted(self._event_stats.iteritems(), key=lambda x: x[1][1]):
            print >> sys.stdout, '"%s", %d, %d' % (name, stat[0], stat[1] / 8)


def convert_fourcc(fourcc_hex):
    """
    Convert a hexidecimal [fourcc](https://en.wikipedia.org/wiki/FourCC) 
    represpentation to a string.
    """
    s = []
    for i in xrange(0, 7, 2):
        n = int(fourcc_hex[i:i+2], 16)
        if n is not 0:
            s.append(chr(n))
    return ''.join(s)


def cache_handle_uri(handle):
    """
    Convert a 'cache handle' from a binary string to a string URI
    """
    handle_hex = binascii.b2a_hex(handle)
    purpose = convert_fourcc(handle_hex[0:8]) # first 4 bytes
    region = convert_fourcc(handle_hex[8:16]) # next 4 bytes
    content_hash = handle_hex[16:]
  
    uri = ''.join([
        'http://',
        region.lower(),
        '.depot.battle.net:1119/',
        content_hash.lower(), '.',
        purpose.lower()
      ])
    return uri


def process_init_data(initdata):
    """
    Take replay init data and convert cache handles to HTTP references.
    """
    translated_handles = []
    for handle in initdata['m_syncLobbyState']['m_gameDescription']['m_cacheHandles']:
        translated_handles.append(cache_handle_uri(handle))
    initdata['m_syncLobbyState']['m_gameDescription']['m_cacheHandles'] = translated_handles
    return initdata


def main():
    """
    Get command line arguments and invoke the command line functionality.
    """
    filters = []
    parser = argparse.ArgumentParser()
    parser.add_argument('replay_file', help='.SC2Replay file to load',
                        nargs='?')
    parser.add_argument("--gameevents", help="print game events",
                        action="store_true")
    parser.add_argument("--messageevents", help="print message events",
                        action="store_true")
    parser.add_argument("--trackerevents", help="print tracker events",
                        action="store_true")
    parser.add_argument("--attributeevents", help="print attributes events",
                        action="store_true")
    parser.add_argument("--header", help="print protocol header",
                        action="store_true")
    parser.add_argument("--details", help="print protocol details",
                        action="store_true")
    parser.add_argument("--initdata", help="print protocol initdata",
                        action="store_true")
    parser.add_argument("--all", help="print all data",
                        action="store_true")
    parser.add_argument("--quiet", help="disable printing",
                        action="store_true")
    parser.add_argument("--stats", help="print stats",
                        action="store_true")
    parser.add_argument("--diff", help="diff two protocols",
                        default=None,
                        action="store")
    parser.add_argument("--versions", help="show all protocol versions",
                        action="store_true")
    parser.add_argument("--types", help="show type information in event output",
                        action="store_true")
    parser.add_argument("--json", help="print output as json",
                        action="store_true")
    parser.add_argument("--ndjson", help="print output as ndjson (newline delimited)",
                        action="store_true")
    args = parser.parse_args()

    # TODO: clean up the command line arguments to allow cleaner sub-command
    # style commands

    # List all protocol versions
    if args.versions:
        files = versions.list_all()
        pattern = re.compile('^protocol([0-9]+).py$')
        captured = []
        for f in files:
            captured.append(pattern.match(f).group(1))
            if len(captured) == 8:
                print >> sys.stdout, captured[0:8]
                captured = []
        print >> sys.stdout, captured
        return

    # Diff two protocols
    if args.diff and args.diff is not None:
        version_list = args.diff.split(',')
        if len(version_list) < 2:
            print >> sys.stderr, "--diff requires two versions separated by comma e.g. --diff=1,2"
            sys.exit(1)
        diff.diff(version_list[0], version_list[1])
        return

    # Check/test the replay file
    if args.replay_file is None:
        print >> sys.stderr, ".S2Replay file not specified"
        sys.exit(1)

    archive = mpyq.MPQArchive(args.replay_file)
    
    filters = []

    if args.json:
        filters.insert(0, JSONOutputFilter(sys.stdout))
    elif args.ndjson:
        filters.insert(0, NDJSONOutputFilter(sys.stdout))
    elif not args.quiet:
        filters.insert(0, PrettyPrintFilter(sys.stdout))

    if args.types:
        filters.insert(0, TypeDumpFilter())

    if args.stats:
        filters.insert(0, StatCollectionFilter())

    def process_event(event):
        for f in filters:
            event = f.process(event)
        
    # Read the protocol header, this can be read with any protocol
    contents = archive.header['user_data_header']['content']
    header = versions.latest().decode_replay_header(contents)
    if args.header:
        process_event(header)

    # The header's baseBuild determines which protocol to use
    baseBuild = header['m_version']['m_baseBuild']
    try:
        protocol = versions.build(baseBuild)
    except:
        print >> sys.stderr, 'Unsupported base build: %d' % baseBuild
        sys.exit(1)

    # Print protocol details
    if args.all or args.details:
        contents = archive.read_file('replay.details')
        details = protocol.decode_replay_details(contents)
        process_event(details)

    # Print protocol init data
    if args.all or args.initdata:
        contents = archive.read_file('replay.initData')
        initdata = protocol.decode_replay_initdata(contents)
        initdata = process_init_data(initdata)
        process_event(initdata)

    # Print game events and/or game events stats
    if args.all or args.gameevents:
        contents = archive.read_file('replay.game.events')
        map(process_event, protocol.decode_replay_game_events(contents))

    # Print message events
    if args.all or args.messageevents:
        contents = archive.read_file('replay.message.events')
        map(process_event, protocol.decode_replay_message_events(contents))

    # Print tracker events
    if args.all or args.trackerevents:
        if hasattr(protocol, 'decode_replay_tracker_events'):
            contents = archive.read_file('replay.tracker.events')
            map(process_event, protocol.decode_replay_tracker_events(contents))

    # Print attributes events
    if args.all or args.attributeevents:
        contents = archive.read_file('replay.attributes.events')
        attributes = protocol.decode_replay_attributes_events(contents)
        process_event(attributes)
        
    for f in filters:
        f.finish()

if __name__ == '__main__':
    main()
