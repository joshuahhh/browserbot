#!/usr/bin/python

from __future__ import with_statement
import cgi, cgitb, os, sys, json, random, time, pprint, redis

from webob import Request, Response
from webob.dec import wsgify
from paste.cgitb_catcher import CgitbMiddleware

# TODO -- epic bug! browser's getting urls like:
# "\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000"
# O_O

# The structure of our Redis database...
# browserbot:
#   request:
#     [request, keyed by intoken]:
#       url       -- url to get (all that the browserbot consumer provides)
#       outtoken  -- current (associated) outtoken (if extant)
#       time      -- unixtime current outtoken was issued (if extant)
#       result    -- answer provided by worker (all that is read by bbot consumer)
#   outtoken:
#     [outtoken]:
#       intoken   -- y'know
#   global:
#     requests_in       \
#     requests_pending  |  -- sets of requests, keyed by intoken
#     requests_out      /       (every request should be in exactly one of these)
#     pending_lock         -- a lock on screwing with things pending / out

def checkRequests(r):
    # revive timed-out pending requests (good to do before servicing a request)
    now = time.time()
    with r.lock("browserbot:global:pending_lock"):
        pipe = r.pipeline()
        for intoken in r.smembers("browserbot:global:requests_pending"):
            if now - float(r.get("browserbot:request:%s:time" % intoken)) > 10:
                # outtoken timed out. rescind it like the dog it is.
                outtoken = r.get("browserbot:request:%s:outtoken" % intoken)
                pipe.delete("browserbot:request:%(intoken)s:outtoken" + " " +
                            "browserbot:request:%(intoken)s:time" + " " +
                            "browserbot:outtoken:%(outtoken)s:intoken"
                            % {"intoken": intoken, "outtoken": outtoken})
                pipe.smove("browserbot:global:requests_pending",
                           "browserbot:global:requests_in",
                           intoken)
        if pipe.command_stack:   # that is, "if we have things to do"
            pipe.execute()

def jsonResponse(value):
    body = json.dumps(value)
    return Response(body=body,
                    headerlist=[
                        ("Content-type", "application/json; charset=utf-8"),
                        ("Content-length", str(len(body))),
                        ])

def tryAgainResponse():
    return jsonResponse({'token': ''})

def getRequestResponse(r):
    intoken = r.spop("browserbot:global:requests_in")
    if not intoken:
        checkRequests(r)
        intoken = r.spop("browserbot:global:requests_in")
    if intoken:
        # We have a request token. This means two things:
        #   1. We have a total responsibility to make sure it doesn't get lost.
        #   2. We don't need to worry about anyone else getting hold of it.

        with r.lock("browserbot:global:pending_lock"):
            outtoken = "out%016x" % random.getrandbits(64)
            url = r.get("browserbot:request:%s:url" % intoken)

            pipe = r.pipeline()
            pipe.sadd("browserbot:global:requests_pending", intoken)
            pipe.mset({("browserbot:request:%s:outtoken" % intoken): outtoken,
                       ("browserbot:request:%s:time" % intoken): time.time(),
                       ("browserbot:outtoken:%s:intoken" % outtoken): intoken})

            return jsonResponse({'token': outtoken, 'url': url, 'debug_token': intoken, "result": pipe.execute()})
    else:
        return tryAgainResponse()

@wsgify
def browserbot_serve(request):
    r = redis.Redis(host="localhost", port=6379)
    if request.environ['REQUEST_METHOD'] == 'GET':
        if request.params.get("action") == "getRequest":
            return getRequestResponse(r)
    elif request.environ['REQUEST_METHOD'] == 'POST':
        if request.params.get("action") == "postResponse":
            outtoken = request.params.get("token")
            result = request.params.get("result")
            if outtoken and result:
                # extract and remove db entry
                with r.lock("browserbot:global:pending_lock"):
                    intoken = r.get("browserbot:outtoken:%s:intoken"
                                        % outtoken)
                    pipe = r.pipeline()
                    pipe.smove("browserbot:global:requests_pending",
                               "browserbot:global:requests_out",
                               intoken)
                    pipe.delete("browserbot:request:%s:url" % intoken,
                                "browserbot:request:%s:outtoken" % intoken,
                                "browserbot:request:%s:time" % intoken,
                                "browserbot:outtoken:%s:intoken" % outtoken)
                    pipe.set("browserbot:request:%s:result" % intoken, result)
                    pipe.execute()
                    # return jsonResponse({"intoken":intoken, "outtoken":outtoken, "result": })
                if request.params.get("another") == "1":
                    return getRequestResponse(r)
                else:
                    return jsonResponse("success!")
    return jsonResponse("end")
browserbot_serve = CgitbMiddleware(browserbot_serve, {'debug':True})

if __name__ == '__main__':
    import flup.server.fcgi
    flup.server.fcgi.WSGIServer(browserbot_serve).run()
