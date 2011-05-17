#!/usr/bin/python

from __future__ import with_statement
import re
from pprint import pprint
import sys
import os
import redis
from contextlib import closing
import json
import random
import time

from twisted.internet import reactor, threads
from twisted.web.client import getPage
from twisted.python.util import println
from twisted.internet.defer import Deferred, DeferredList, succeed

from browserbot_client_redis import BrowserbotClientRedis

# TODO: A status page would be nice.

USE_DB = True
APP_NAME = "tcrawl"
userdb = redis.Redis(host='localhost', port=6379)

downloads = BrowserbotClientRedis(userdb, maxThreads=40)

def getFollowersFromMobilePage(page):
    return re.findall("<div class='list-tweet' id='user_([^']*)'>", page)

def getCursorFromMobilePage(page):
    #match = re.search("<a href=\"/[^/]*/followers\?cursor=([0-9]*)\">more</a>", page)
    match = re.search("/followers\?cursor=([0-9]*)\">more</a>", page)
    return match.group(1) if match else None

def getFollowerSet(name, cursor="-1"):
    print "getFollowerSet!"
    urlTemplate = "http://mobile.twitter.com/%s/followers?cursor=%s&offset=%i"
    partialResults = {}
    deferreds = []
    outCursor = [None]
    for offset in range(0,100,20):
        url = urlTemplate % (name, cursor, offset)
        def gotPageCallback(page, offset=offset):
            if page:
                partialResults[offset] = getFollowersFromMobilePage(page)
                if offset == 80:
                    # We might have a cursor!
                    potentialCursor = getCursorFromMobilePage(page)
                    #print "potentialCursor =", potentialCursor
                    if potentialCursor:
                        outCursor[0] = potentialCursor
            else:
                # something's up, I guess?
                raise Error("gotPageCallback got an empty page")

        def gotPageErrback(error):
            if error.getErrorMessage() == "302 Found":
                # Oh, it's just a dude with protected tweets. Screw 'em.
                return
            else:
                print "AW CRAP NAW:", error.getErrorMessage()
        if url == "":
            print "EMPTY URL? WHATTTTT?"
            print "name =", name
            print "offset =", offset
        d = downloads.addRequest(url).addCallbacks(gotPageCallback, gotPageErrback)
        deferreds.append(d)
    d = Deferred()
    def gotAllPagesCallback(result):
        if partialResults:
            followers = sum(partialResults.values(), [])
            d.callback((followers, outCursor[0]))
    DeferredList(deferreds).addCallback(gotAllPagesCallback)
    return d

def getFollowers(name):
    def gotFollowersCallback(result):
        print "gotFollowersCallback!"
        if USE_DB:
            userdb.sadd(APP_NAME + ":users_crawled", name)
            for follower in result:
                userdb.sadd(APP_NAME + ":users:" + name + ":followers", follower)
        return result
    return getFollowersStartingAt(name, "-1").addCallback(gotFollowersCallback)

def getFollowersStartingAt(name, startingCursor):
    print "getFollowersStartingAt!"
    if USE_DB:
        if userdb.exists(APP_NAME + ":users:" + name + ":followers"):
            return succeed(userdb.smembers(APP_NAME + ":users:" + name + ":followers"))

    # Here's a good example of how screwed-up-looking code can get
    # when you have to make yer asynchronous calls AFTER you define
    # your callbacks...
    
    outDeferred = Deferred()
    def gotFollowerSetCallback(result):
        print "gotFollowerSetCallback!"
        followerSet, cursor = result
        if cursor:
            def gotRestOfFollowersCallback(restOfFollowers):
                print "gotRestOfFollowersCallback!"
                outDeferred.callback(followerSet + restOfFollowers)
            getFollowersStartingAt(name, cursor).addCallback(gotRestOfFollowersCallback)
        else:
            outDeferred.callback(followerSet)
    getFollowerSet(name, startingCursor).addCallback(gotFollowerSetCallback)  
    return outDeferred

i = 0

class GetFollowers(object):
    def __init__(self):
        self.followerData = {}
        self.namesSeen = set()
        self.namesCrawled = set()
        self.todo = 0

    def go(self):
        if len(sys.argv) > 1:
            def pprintIdentity(x):
                pprint(x)
                return x
            return getFollowers(sys.argv[1])
        else:
            return self.spiderFollowers(["nickeliferous"], 3)

    def spiderFollowers(self, names, level):
        print "Spidering at level %i" % level
        if level == 0:
            return succeed(None)

        deferreds = []
        for name in names:
            def gotFollowersCallback(results, name=name):
                self.followerData[name] = results
                resultsSet = set(results)
                self.namesSeen |= resultsSet
                self.namesCrawled.add(name)
                
                newSet = resultsSet - self.namesCrawled
                return self.spiderFollowers(newSet, level-1)
            d = getFollowers(name)
            d.addCallback(gotFollowersCallback)
            deferreds.append(d)
        d = Deferred()
        DeferredList(deferreds).addCallback(lambda _: d.callback(self.followerData))
        return d


gf = GetFollowers()
def finalCallback(result):
    reactor.stop()
    print "and the winner is:"
    pprint(result)

reactor.callWhenRunning(lambda : gf.go().addCallback(finalCallback))
reactor.run()
