from __future__ import with_statement
import os, time, random, json
from twisted.internet.threads import deferToThread
from twisted.internet.defer import Deferred
import redis

# TODO: get rid of "deferToThread"s
class BrowserbotClientRedis(object):
    # A bit of terminology here: Every request ends up being
    # associated with two different deferreds:
    #   * An /external/ deferred, which we return to the consumer when
    #     they make a request.
    #   * An /internal/ deferred, which is returned to us by
    #     deferToThread.
    
    # Through chaining, the triggering of the internal deferred causes
    # the triggering of the external deferred. Why two deferreds,
    # then? Simply because we can't give the consumer the
    # deferToThread deferred until we run deferToThread, which could
    # happen later (that's what the queue is for!).
    
    def __init__(self, redis, maxThreads = 10):
        self.redis = redis
        self.maxThreads = maxThreads
        self.requests = [] # queued requests -- (url, extDeferred)
        self.deferreds = [] # waiting requests -- (intDeferred)
    
    def addRequest(self, url):
        try:
            url.decode('ascii')
            extDeferred = Deferred()
            self.requests.append((url, extDeferred))
            self._manageQueue()
            return extDeferred
        except UnicodeDecodeError:
            print "non-ASCII url encountered! -", url

    def _manageQueue(self):
        # make sure we have as many threads going as we can
        while self.requests and len(self.deferreds) < self.maxThreads:
            url, extDeferred = self.requests.pop()
            intDeferred = self._getPage(url)
            intDeferred.chainDeferred(extDeferred)
            def gotPageCallback(value, intDeferred=intDeferred):
                self.deferreds.remove(intDeferred)
                self._manageQueue()
            intDeferred.addCallback(gotPageCallback)
            self.deferreds.append(intDeferred)
            print "finished managing; %i requests, %i deferreds" % (len(self.requests), len(self.deferreds))

    def _getPage(self, url):
        intoken = str("in%016x" % random.getrandbits(64))
        pipe = self.redis.pipeline()
        pipe.sadd("browserbot:global:requests_in", intoken)
        pipe.set("browserbot:request:%s:url" % intoken, url)
        pipe.execute()
        return deferToThread(self._watchForTokenBlocking, intoken)

    def _watchForTokenBlocking(self, intoken):
        while True:
            result = self.redis.get("browserbot:request:%s:result" % intoken)
            if result:
                pipe = self.redis.pipeline()
                pipe.delete("browserbot:request:%s:result" % intoken)
                pipe.srem("browserbot:global:requests_out", intoken)
                pipe.execute()
                return json.read(result)
            else:
                time.sleep(1)  # wait a second before checking again
