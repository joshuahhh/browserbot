from __future__ import with_statement
from pprint import pprint
from collections import defaultdict
from contextlib import closing
import redis


APP_NAME = "tcrawl"
r = redis.Redis(host='browser.bot.nu', port=6379)

print "Running..."

users_crawled = r.smembers(APP_NAME + ":users_crawled")
user_followers = defaultdict(list)
user_connection_counts = defaultdict(int)

# GET HELLA DATA

for name in users_crawled:
    followers = r.smembers(APP_NAME + ":users:" + name + ":followers")
    user_followers[name] = followers
    user_connection_counts[name] += len(followers)
    for follower in user_followers[name]:
        user_connection_counts[follower] += 1

dudesICareAbout = set(name for name, count in user_connection_counts.iteritems()
                           if count >= 2)

print "I care about " + str(len(dudesICareAbout)) + " dudes."
with open("newout2.dot","w") as f:
    f.write("digraph G {\n")
    for name in dudesICareAbout:
        print "processing " + name
        for follower in dudesICareAbout & r.smembers(APP_NAME + ":users:" + name + ":followers"):
#        for follower in r.smembers(APP_NAME + ":users:" + name + ":followers"):
            print "connect to " + follower
            f.write('"%s" -> "%s" [ arrowhead="dot" ];\n' % (follower, name))
            #f.write('"%s" [ label="",shape="point",width=".1",height=".1" ];\n' % name)
    f.write("}")
